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
from sqlfun.models import SqlFunDefinition

if TYPE_CHECKING:
    from django.db.migrations.graph import Node


def get_previous_sql_definition(cls: SqlFun):
    try:
        sqlfun_definition = SqlFunDefinition.objects.get(
            function_name=cls.get_function_name_from_sql()
        )
        return sqlfun_definition.sql_definition
    except SqlFunDefinition.DoesNotExist:
        return None


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


def get_migration_operations() -> dict[str, list[migrations.RunSQL]]:
    migration_operations = defaultdict(list)

    for sqlfun_cls in SqlFun._registry:
        app_label = get_app_label_for_cls(sqlfun_cls)
        function_name = sqlfun_cls.get_function_name_from_sql()
        current_sql = normalize_sql(sqlfun_cls.sql)
        previous_sql = get_previous_sql_definition(sqlfun_cls)

        if current_sql != previous_sql:
            drop_function_sql = f'DROP FUNCTION IF EXISTS {function_name};'
            migration_operations[app_label].append(migrations.RunSQL(
                sql=sqlfun_cls.sql,
                reverse_sql=previous_sql or drop_function_sql,
            ))

    for stored_function in SqlFunDefinition.objects.all():
        app_label = stored_function.app_label
        if not any(
            func.get_function_name_from_sql() == stored_function.function_name
            for func in SqlFun._registry
        ):
            operation = migrations.RunSQL(
                sql=f'DROP FUNCTION IF EXISTS {stored_function.function_name};',
            )
            migration_operations[app_label].append(operation)

    return migration_operations


def create_custom_migration(
    name: str,
    app_label: str,
    dependencies: list['Node'],
    operations: list[migrations.RunSql],
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
    operations: list[migrations.RunSql],
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
    for sqlfun_cls in SqlFun._registry:
        function_name = sqlfun_cls.get_function_name_from_sql()
        current_sql = normalize_sql(sqlfun_cls.sql)
        app_label = get_app_label_for_cls(sqlfun_cls)

        definition, created = SqlFunDefinition.objects.get_or_create(
            function_name=function_name,
            app_label=app_label,
        )
        definition.sql_definition = current_sql
        definition.save()

    # Remove deleted functions from the SqlFunDefinition model
    for stored_function in SqlFunDefinition.objects.all():

        if not any(
            func.get_function_name_from_sql() == stored_function.function_name
            for func in SqlFun._registry
        ):
            stored_function.delete()


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
        is_dry_run=False,
        stdout=None,
) -> list[pathlib.Path]:
    app_to_operations_map = get_migration_operations()

    if not app_to_operations_map:
        return

    migration_paths = []

    for app_label, app_to_operations_map in app_to_operations_map.items():
        if stdout:
            stdout.write(f"[sqlfun] Generating migration for app '{app_label}'")

        next_migration_number = get_next_migration_number(app_label)
        migration_name = (
            custom_name or
            f"update_sqlfun_functions_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        )

        migration_paths.append(
            generate_migration(
                f'{next_migration_number:04}_{migration_name}',
                app_label,
                app_to_operations_map,
                is_dry_run
            )
        )

    update_sqlfun_definition_model()

    return migration_paths
