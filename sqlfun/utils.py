from __future__ import annotations

import inspect
import os
import pathlib
import re
import textwrap
from collections import defaultdict
from typing import TYPE_CHECKING, Optional

import sqlparse
from django.apps import apps as django_apps
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections, migrations
from django.db.migrations.writer import MigrationWriter
from django.utils import timezone

from sqlfun.core import SqlFun
from sqlfun.introspection import introspect_signature
from sqlfun.naming import (
    SqlFunConfigurationError,
    SqlFunError,
    ensure_or_replace,
    normalize_identity,
)
from sqlfun.operations import CreateFunction, DropFunction
from sqlfun.state import get_replayed_state, load_migration_graph

if TYPE_CHECKING:
    from django.db.migrations.graph import Node


_DOLLAR_QUOTED_BODY_RE = re.compile(r'(\$\w*\$)(.*?)\1', re.DOTALL)


def _dedent_dollar_quoted_body(match: re.Match) -> str:
    delimiter = match.group(1)
    return delimiter + textwrap.dedent(match.group(2)) + delimiter


def normalize_sql(sql: str) -> str:
    """Format SQL for change-detection comparison.

    sqlparse's reindent treats a dollar-quoted function body ($$...$$) as
    one opaque literal and never reformats its interior, so re-indenting the
    whole SQL text (which shifts every line inside the body by the same
    amount) would otherwise still read as a change. Strip the body's common
    leading indentation after formatting so only the dollar-quote delimiters
    remain sensitive to reindent -- deliberately less aggressive than
    collapsing all interior whitespace, which would hide real changes inside
    string literals or whitespace-significant bodies (e.g. plpython3u).
    """
    formatted = sqlparse.format(sql, reindent=True, keyword_case='upper')
    return _DOLLAR_QUOTED_BODY_RE.sub(_dedent_dollar_quoted_body, formatted)


def get_app_name(filepath: str) -> str | None:
    """
    Returns the name of the Django app that contains the module at the given filepath.
    Returns None if the module is not part of a Django app.
    """
    while filepath != '/':
        filepath, module_name = os.path.split(filepath)
        if module_name == 'apps.py':
            app_name = os.path.basename(filepath)
            if app_name != '__init__':
                return app_name
        elif module_name == 'models.py':
            app_name = os.path.basename(filepath)
            if app_name != '__init__':
                return app_name
    return None


def get_app_label_for_cls(sqlfun_cls: SqlFun) -> str | None:
    return sqlfun_cls.app_label or get_app_name(inspect.getfile(sqlfun_cls))


def _registered_functions(in_scope) -> tuple[dict, set[str]]:
    """Resolve each registered class to its identity without touching the
    database.

    Returns the in-scope classes keyed by identity, plus every identity
    that is registered anywhere. A class that belongs to an app outside
    the requested ones cannot fail the run, but a function whose class moved
    to such an app must still not look deleted in the app it came from.
    """
    by_identity = defaultdict(list)
    for sqlfun_cls in SqlFun._registry:
        app_label = get_app_label_for_cls(sqlfun_cls)
        try:
            name = sqlfun_cls.get_function_name_from_sql()
            identity = normalize_identity(name)
        except SqlFunError:
            if in_scope(app_label):
                raise
            continue
        by_identity[identity].append((sqlfun_cls, name, app_label))

    registered = {}
    for identity, claims in by_identity.items():
        if not any(in_scope(app_label) for _, _, app_label in claims):
            continue
        if len(claims) > 1:
            (first_cls, first_name, _), (other_cls, other_name, _) = claims[:2]
            raise SqlFunConfigurationError(
                f'SqlFun classes {first_cls.__name__!r} ({first_name!r}) and '
                f'{other_cls.__name__!r} ({other_name!r}) both normalize to the '
                f'function identity {identity!r}. Rename one of the SQL '
                'functions so each registered class has a distinct identity.'
            )
        sqlfun_cls, name, app_label = claims[0]
        if app_label is None:
            raise SqlFunConfigurationError(
                f'SqlFun class {sqlfun_cls.__name__!r} is not inside a '
                'recognizable Django app (no apps.py or models.py above it). '
                "Set an explicit app_label on the class, e.g. app_label = 'myapp'."
            )
        registered[identity] = claims[0]
    return registered, set(by_identity)


def get_migration_operations(
    database=DEFAULT_DB_ALIAS,
    loader=None,
    app_labels=None,
) -> dict[str, list[migrations.operations.base.Operation]]:
    """Build the pending sqlfun operations, grouped by app.

    With ``app_labels``, functions of other apps are neither introspected
    nor validated, matching Django's scoped makemigrations.
    """
    operations, _ = _plan_migrations(database, loader, app_labels)
    return operations


def _plan_migrations(database, loader, app_labels):
    """Pending operations per app, plus the migrations in other apps that
    each app's new migration must depend on."""

    def in_scope(app_label):
        return not app_labels or app_label in app_labels

    state = get_replayed_state(loader=loader)
    registered, all_identities = _registered_functions(in_scope)

    create_operations = defaultdict(list)
    drop_operations = defaultdict(list)
    dependencies = defaultdict(list)
    app_order = []

    def remember_app(app_label):
        if app_label not in app_order:
            app_order.append(app_label)

    for identity, (sqlfun_cls, name, app_label) in registered.items():
        previous = state.get(identity)
        if previous is not None and (
            normalize_sql(previous.sql) == normalize_sql(sqlfun_cls.sql)
        ):
            # unchanged since its migration was written: no introspection,
            # no queries -- the steady state is database-free
            continue
        try:
            ensure_or_replace(sqlfun_cls.sql)
            signature = introspect_signature(
                sqlfun_cls.sql, name, conn=connections[database]
            )
        except SqlFunError as error:
            raise SqlFunError(
                f'SqlFun class {sqlfun_cls.__name__!r}: {error}'
            ) from error
        remember_app(app_label)
        if previous is not None and previous.app_label != app_label:
            # the class moved apps: without this, replay and migrate may
            # both run the old app's definition after this one
            if previous.node not in dependencies[app_label]:
                dependencies[app_label].append(previous.node)
        if previous is None:
            # nothing in the migration history accounts for the live
            # function(s) introspection had to drop (a RunSQL-era definition
            # or hand-made drift), so the migration must drop them too:
            # CREATE OR REPLACE cannot change a signature
            create_operations[app_label].extend(
                DropFunction(
                    name=identity,
                    identity_arguments=live.identity_arguments,
                    sql=live.sql,
                )
                for live in signature.replaced
            )
        create_operations[app_label].append(
            CreateFunction(
                name=identity,
                identity_arguments=signature.identity_arguments,
                result_type=signature.result_type,
                sql=sqlfun_cls.sql,
                previous_sql=previous.sql if previous else None,
                previous_identity_arguments=(
                    previous.identity_arguments if previous else None
                ),
                previous_result_type=previous.result_type if previous else None,
            )
        )

    for identity, stored in state.items():
        if identity not in all_identities and in_scope(stored.app_label):
            remember_app(stored.app_label)
            drop_operations[stored.app_label].append(
                DropFunction(
                    name=identity,
                    identity_arguments=stored.identity_arguments,
                    sql=stored.sql,
                )
            )

    operations = {
        app_label: drop_operations[app_label] + create_operations[app_label]
        for app_label in app_order
    }
    return operations, {app_label: dependencies[app_label] for app_label in app_order}


def create_custom_migration(
    name: str,
    app_label: str,
    dependencies: list['Node'],
    operations: list[migrations.operations.base.Operation],
) -> migrations.Migration:
    SqlFunMigration = type(
        'SqlFunMigration',
        (migrations.Migration,),
        {'dependencies': dependencies, 'operations': operations},
    )
    return SqlFunMigration(name=name, app_label=app_label)


def _app_migrations_dir(app_label: str) -> pathlib.Path:
    """Return the directory Django's migration writer resolves for an app."""
    migration = migrations.Migration('_sqlfun_path_probe', app_label)
    return _migration_path(migration).parent


def _migration_path(migration: migrations.Migration) -> pathlib.Path:
    """Return Django's write path with sqlfun-specific error handling."""
    app_label = migration.app_label
    try:
        django_apps.get_app_config(app_label)
    except LookupError as error:
        raise SqlFunConfigurationError(
            f'Cannot write a sqlfun migration for {app_label!r}: it is not '
            'an installed Django app.'
        ) from error

    is_explicit = app_label in settings.MIGRATION_MODULES
    if app_label == 'sqlfun' and not is_explicit:
        raise SqlFunConfigurationError(
            "Refusing to write a migration into the installed 'sqlfun' "
            'package. This happens when a function was last created by a '
            'migration inside sqlfun itself; hand-write the migration in one '
            'of your own apps instead.'
        )

    try:
        return pathlib.Path(MigrationWriter(migration).path)
    except ValueError as error:
        raise SqlFunConfigurationError(
            f'Cannot write a sqlfun migration for {app_label!r}: {error}'
        ) from error


def write_migration(migration_path: pathlib.Path, migration: migrations.Migration):
    writer = MigrationWriter(migration)
    migration_file_content = writer.as_string()
    migration_path.parent.mkdir(parents=True, exist_ok=True)
    # a migrations dir without __init__.py is invisible to MigrationLoader
    (migration_path.parent / '__init__.py').touch(exist_ok=True)
    with migration_path.open('w') as migration_file:
        migration_file.write(migration_file_content)


def generate_migration(
    migration_name: str,
    app_label: str,
    operations: list[migrations.operations.base.Operation],
    is_dry_run: bool = False,
    loader=None,
    extra_dependencies: list['Node'] = (),
) -> pathlib.Path:
    if loader is None:
        loader = load_migration_graph()
    latest_leaf_node: Optional['Node'] = loader.graph.leaf_nodes(app_label)

    migration = create_custom_migration(
        name=migration_name,
        app_label=app_label,
        dependencies=[*(latest_leaf_node or []), *extra_dependencies],
        operations=operations,
    )
    migration_path = _migration_path(migration)

    if not is_dry_run:
        write_migration(migration_path, migration)

    return migration_path


def get_next_migration_number(app_label: str) -> int:
    migrations_directory = _app_migrations_dir(app_label)
    existing_migrations = migrations_directory.glob('*.py')
    migration_numbers = []

    for migration in existing_migrations:
        match = re.match(r'^(\d+)_', migration.name)
        if match:
            migration_numbers.append(int(match.group(1)))

    return max(migration_numbers, default=0) + 1


def make_sqlfun_migrations(
    custom_name=None,
    *,
    app_labels=None,
    is_dry_run=False,
    stdout=None,
    database=DEFAULT_DB_ALIAS,
) -> list[pathlib.Path]:
    loader = load_migration_graph()
    app_to_operations_map, app_to_dependencies = _plan_migrations(
        database,
        loader,
        app_labels,
    )

    migration_paths = []

    for app_label, operations in app_to_operations_map.items():
        if stdout:
            verb = 'Would generate' if is_dry_run else 'Generating'
            stdout.write(f"[sqlfun] {verb} migration for app '{app_label}'")

        next_migration_number = get_next_migration_number(app_label)
        migration_name = (
            custom_name
            or f'update_sqlfun_functions_{timezone.now().strftime("%Y%m%d_%H%M%S")}'
        )

        migration_paths.append(
            generate_migration(
                f'{next_migration_number:04}_{migration_name}',
                app_label,
                operations,
                is_dry_run,
                loader=loader,
                extra_dependencies=app_to_dependencies[app_label],
            )
        )

    return migration_paths
