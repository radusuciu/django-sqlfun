from __future__ import annotations

import inspect
import os
import pathlib
import re
from collections import defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING, Optional

import sqlparse
from django.conf import settings
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.writer import MigrationWriter
from django.utils import timezone

from sqlfun.core import SqlFun
from sqlfun.introspection import Signature, introspect_signature
from sqlfun.models import SqlFunDefinition
from sqlfun.naming import SqlFunError

if TYPE_CHECKING:
    from django.db.migrations.graph import Node


def normalize_sql(sql: str) -> str:
    return sqlparse.format(sql, reindent=True, keyword_case='upper')


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
            signature = introspect_signature(sqlfun_cls.sql, name)
        except SqlFunError as error:
            raise SqlFunError(f'SqlFun class {sqlfun_cls.__name__!r}: {error}') from error
        pairs.append((sqlfun_cls, signature))
    return pairs


def get_previous_definition(canonical_name: str) -> SqlFunDefinition | None:
    try:
        return SqlFunDefinition.objects.get(function_name=canonical_name)
    except SqlFunDefinition.DoesNotExist:
        return None


def _find_matching_legacy_row(current_sql: str) -> SqlFunDefinition | None:
    """Match a pre-identity-columns row by its stored SQL text.

    Legacy rows keep a regex-era function_name that never equals the
    canonical name, but store the same SQL text — a match after
    re-normalization means the registered function is unchanged since that
    version stored it. Both sides are re-normalized with the installed
    sqlparse because its formatting can differ from the version that wrote
    the row.
    """
    for row in SqlFunDefinition.objects.filter(identity_arguments='', result_type=''):
        if normalize_sql(row.sql_definition) == current_sql:
            return row
    return None


def _build_operation_for_function(
    sqlfun_cls: SqlFun, signature: Signature
) -> tuple[migrations.RunSQL | None, SqlFunDefinition | None]:
    """Return (operation, claimed_legacy_row) for a registered function.

    The operation is None if the function is unchanged; claimed_legacy_row
    is the legacy row matched by SQL text (also meaning unchanged), so the
    caller can exclude it from deleted-function handling.
    """
    current_sql = normalize_sql(sqlfun_cls.sql)
    previous = get_previous_definition(signature.name)

    # re-normalize the stored text: rows written by a different sqlparse
    # version may differ only in formatting
    if previous is not None and current_sql == normalize_sql(previous.sql_definition):
        return None, None

    if previous is None:
        legacy = _find_matching_legacy_row(current_sql)
        if legacy is not None:
            # unchanged since a pre-identity version stored it; the
            # bookkeeping pass rewrites the row in canonical form
            return None, legacy
        return migrations.RunSQL(
            sql=sqlfun_cls.sql,
            reverse_sql=f'DROP FUNCTION IF EXISTS {signature.drop_clause};',
        ), None

    signature_changed = (
        previous.identity_arguments != signature.identity_arguments
        or previous.result_type != signature.result_type
    )

    if not signature_changed:
        return migrations.RunSQL(
            sql=sqlfun_cls.sql,
            reverse_sql=previous.sql_definition,
        ), None

    previous_drop = (
        f'{previous.function_name}({previous.identity_arguments})'
        if previous.identity_arguments
        else previous.function_name
    )
    return migrations.RunSQL(
        sql=[
            f'DROP FUNCTION IF EXISTS {previous_drop};',
            sqlfun_cls.sql,
        ],
        reverse_sql=[
            f'DROP FUNCTION IF EXISTS {signature.drop_clause};',
            previous.sql_definition,
        ],
    ), None


def _build_deleted_function_operations(
    registered_canonical: set[str], stdout=None, claimed_legacy_pks: set = frozenset()
) -> Iterator[tuple[str | None, migrations.RunSQL]]:
    """Yield (app_label, drop op) for stored functions no longer registered.

    Drops are built from the stored identity columns — no parsing, no
    re-execution of stored SQL. A legacy row that predates the identity
    columns (empty identity_arguments) cannot be dropped unambiguously: if a
    registered function claimed it by SQL text it is skipped silently,
    otherwise it is skipped with a warning and left for manual cleanup.
    """
    for stored in SqlFunDefinition.objects.all():
        if stored.function_name in registered_canonical:
            continue
        if stored.pk in claimed_legacy_pks:
            continue
        if not stored.identity_arguments and stored.result_type == '':
            # legacy row with no captured signature — cannot build a safe DROP
            if stdout:
                stdout.write(
                    f"[sqlfun] Skipping DROP for '{stored.function_name}': no stored "
                    'signature (legacy row). Drop it manually if the function is gone.'
                )
            continue
        yield stored.app_label, migrations.RunSQL(
            sql=f'DROP FUNCTION IF EXISTS {stored.function_name}({stored.identity_arguments});',
            reverse_sql=stored.sql_definition,
        )


def get_migration_operations(stdout=None) -> dict[str, list[migrations.RunSQL]]:
    migration_operations = defaultdict(list)
    pairs = _introspect_registered()
    registered_canonical = {signature.name for _, signature in pairs}

    claimed_legacy_pks = set()
    for sqlfun_cls, signature in pairs:
        operation, claimed_legacy = _build_operation_for_function(sqlfun_cls, signature)
        if claimed_legacy is not None:
            claimed_legacy_pks.add(claimed_legacy.pk)
        if operation is not None:
            migration_operations[get_app_label_for_cls(sqlfun_cls)].append(operation)

    for app_label, operation in _build_deleted_function_operations(
        registered_canonical, stdout, claimed_legacy_pks
    ):
        migration_operations[app_label].append(operation)

    return migration_operations


def create_custom_migration(
    name: str,
    app_label: str,
    dependencies: list['Node'],
    operations: list[migrations.RunSQL],
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
    operations: list[migrations.RunSQL],
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


def update_sqlfun_definition_model():
    pairs = _introspect_registered()
    registered_canonical = {signature.name for _, signature in pairs}

    for sqlfun_cls, signature in pairs:
        SqlFunDefinition.objects.update_or_create(
            function_name=signature.name,
            defaults={
                'sql_definition': normalize_sql(sqlfun_cls.sql),
                'app_label': get_app_label_for_cls(sqlfun_cls),
                'identity_arguments': signature.identity_arguments,
                'result_type': signature.result_type,
            },
        )

    # Remove rows for functions that are no longer registered (incl. legacy-named rows)
    for stored in SqlFunDefinition.objects.all():
        if stored.function_name not in registered_canonical:
            stored.delete()


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
    app_to_operations_map = get_migration_operations(stdout=stdout)
    nothing_changed = not app_to_operations_map

    if app_labels:
        app_to_operations_map = {
            app_label: operations
            for app_label, operations in app_to_operations_map.items()
            if app_label in app_labels
        }

    if not app_to_operations_map:
        # even with no operations, legacy rows claimed by SQL text still need
        # rewriting in canonical form -- but only when nothing changed at all:
        # an app_labels filter may have dropped operations whose migrations
        # were never written, and bookkeeping would consume their detection
        if nothing_changed and not is_dry_run:
            update_sqlfun_definition_model()
        return []

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

    if not is_dry_run:
        update_sqlfun_definition_model()

    return migration_paths
