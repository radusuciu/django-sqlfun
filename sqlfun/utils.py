from __future__ import annotations

import inspect
import os
import pathlib
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Optional

import sqlparse
from django.conf import settings
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.writer import MigrationWriter
from django.utils import timezone

from sqlfun.core import SqlFun
from sqlfun.introspection import Signature, introspect_signature
from sqlfun.naming import SqlFunError, ensure_or_replace
from sqlfun.operations import CreateFunction, DropFunction
from sqlfun.state import get_replayed_state

if TYPE_CHECKING:
    from django.db.migrations.graph import Node


_DOLLAR_QUOTED_BODY_RE = re.compile(r'(\$\w*\$)(.*?)\1', re.DOTALL)


def normalize_sql(sql: str) -> str:
    """Format SQL for change-detection comparison.

    sqlparse's reindent treats a dollar-quoted function body ($$...$$) as
    one opaque literal and never reformats its interior, so a purely
    cosmetic whitespace change inside the body would otherwise still read
    as a change. Collapse interior whitespace after formatting so only the
    dollar-quote delimiters remain sensitive to reindent.
    """
    formatted = sqlparse.format(sql, reindent=True, keyword_case='upper')
    return _DOLLAR_QUOTED_BODY_RE.sub(
        lambda match: (
            match.group(1) + re.sub(r'\s+', ' ', match.group(2)).strip() + match.group(1)
        ),
        formatted,
    )


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


def _introspect_registered() -> list[tuple[SqlFun, Signature]]:
    """Introspect every registered class once; returns (class, signature) pairs."""
    pairs = []
    for sqlfun_cls in SqlFun._registry:
        name = sqlfun_cls.get_function_name_from_sql()
        try:
            ensure_or_replace(sqlfun_cls.sql)
            signature = introspect_signature(sqlfun_cls.sql, name)
        except SqlFunError as error:
            raise SqlFunError(f'SqlFun class {sqlfun_cls.__name__!r}: {error}') from error
        pairs.append((sqlfun_cls, signature))
    return pairs


def get_migration_operations() -> dict[str, list[migrations.operations.base.Operation]]:
    migration_operations = defaultdict(list)
    pairs = _introspect_registered()
    registered_canonical = {signature.name for _, signature in pairs}
    state = get_replayed_state()

    for sqlfun_cls, signature in pairs:
        previous = state.get(signature.name)
        if previous is not None and (
            normalize_sql(previous.sql) == normalize_sql(sqlfun_cls.sql)
        ):
            continue
        migration_operations[get_app_label_for_cls(sqlfun_cls)].append(
            CreateFunction(
                name=signature.name,
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

    for name, stored in state.items():
        if name not in registered_canonical:
            migration_operations[stored.app_label].append(
                DropFunction(
                    name=name,
                    identity_arguments=stored.identity_arguments,
                    sql=stored.sql,
                )
            )

    return migration_operations


def create_custom_migration(
    name: str,
    app_label: str,
    dependencies: list['Node'],
    operations: list[migrations.operations.base.Operation],
) -> migrations.Migration:
    SqlFunMigration = type('SqlFunMigration', (migrations.Migration,), {
        'dependencies': dependencies,
        'operations': operations
    })
    return SqlFunMigration(name=name, app_label=app_label)


def write_migration(migration_path: pathlib.Path, migration: migrations.Migration):
    writer = MigrationWriter(migration)
    migration_file_content = writer.as_string()
    migration_path.parent.mkdir(parents=True, exist_ok=True)
    with migration_path.open('w') as migration_file:
        migration_file.write(migration_file_content)


def generate_migration(
    migration_name: str,
    app_label: str,
    operations: list[migrations.operations.base.Operation],
    is_dry_run: bool = False,
) -> pathlib.Path:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    latest_leaf_node: Optional['Node'] = loader.graph.leaf_nodes(app_label)

    migration = create_custom_migration(
        name=migration_name,
        app_label=app_label,
        dependencies=latest_leaf_node or [],
        operations=operations,
    )

    migrations_directory = pathlib.Path(settings.BASE_DIR) / app_label / 'migrations'
    migration_path = migrations_directory / f'{migration_name}.py'

    if not is_dry_run:
        write_migration(migration_path, migration)

    return migration_path


def get_next_migration_number(app_label: str) -> int:
    migrations_directory = pathlib.Path(settings.BASE_DIR) / app_label / 'migrations'
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
) -> list[pathlib.Path]:
    app_to_operations_map = get_migration_operations()

    if app_labels:
        app_to_operations_map = {
            app_label: operations
            for app_label, operations in app_to_operations_map.items()
            if app_label in app_labels
        }

    migration_paths = []

    for app_label, operations in app_to_operations_map.items():
        if stdout:
            verb = 'Would generate' if is_dry_run else 'Generating'
            stdout.write(f"[sqlfun] {verb} migration for app '{app_label}'")

        next_migration_number = get_next_migration_number(app_label)
        migration_name = (
            custom_name or
            f"update_sqlfun_functions_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        )

        migration_paths.append(
            generate_migration(
                f'{next_migration_number:04}_{migration_name}',
                app_label,
                operations,
                is_dry_run
            )
        )

    return migration_paths
