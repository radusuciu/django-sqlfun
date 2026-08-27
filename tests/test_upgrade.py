import textwrap

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.state import ProjectState

from sqlfun import SqlFun
from sqlfun.operations import CreateFunction
from sqlfun.utils import get_migration_operations

from .utils import function_exists, remove_test_migration, write_test_migration

UPGRADE_SQL = (
    'CREATE OR REPLACE FUNCTION upgrade_fn(a integer) RETURNS integer '
    'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
)


@pytest.mark.django_db
def test_runsql_history_yields_baseline_create_that_applies_cleanly():
    """The in-place upgrade path: a pre-0.2.0 project has only plain RunSQL
    migrations, which contribute nothing to replayed state, so every
    registered function gets a baseline CreateFunction with no previous_*.
    Applying that baseline against the already-populated database must be a
    no-op re-create."""

    class UpgradeFn(SqlFun):
        app_label = 'test_project'
        sql = UPGRADE_SQL

    old_style = write_test_migration(
        'test_project', '0951_old_style_runsql',
        textwrap.dedent(f'''\
            from django.db import migrations


            class Migration(migrations.Migration):
                dependencies = [('test_project', '0001_initial')]
                operations = [
                    migrations.RunSQL(
                        sql={UPGRADE_SQL!r},
                        reverse_sql='DROP FUNCTION IF EXISTS upgrade_fn(integer);',
                    ),
                ]
            '''),
    )
    try:
        call_command('migrate')
        assert function_exists('upgrade_fn')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'upgrade_fn'
        ]
        assert len(operations) == 1
        operation = operations[0]
        assert isinstance(operation, CreateFunction)
        assert operation.previous_sql is None

        with connection.schema_editor() as schema_editor:
            operation.database_forwards(
                'test_project', schema_editor, ProjectState(), ProjectState()
            )
        assert function_exists('upgrade_fn')
    finally:
        UpgradeFn.deregister()
        remove_test_migration('test_project', old_style)


@pytest.mark.django_db
def test_delete_model_migration_applies_over_populated_table():
    """0003 must drop the table even when it holds pre-upgrade rows."""
    call_command('migrate', 'sqlfun', '0002_signature_columns')
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO sqlfun_sqlfundefinition "
            "(function_name, sql_definition, app_label, identity_arguments, result_type) "
            "VALUES ('public.legacy_fn', 'CREATE OR REPLACE FUNCTION ...', "
            "'test_project', 'a integer', 'integer')"
        )
    call_command('migrate', 'sqlfun')
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('sqlfun_sqlfundefinition')")
        assert cursor.fetchone()[0] is None


def test_drop_is_routed_to_the_app_that_defined_the_function():
    """A function whose last CreateFunction lives in the sqlfun app must have
    its DropFunction routed there, not to the app of some registered class."""
    path = write_test_migration(
        'sqlfun', '0952_routing_probe',
        textwrap.dedent('''\
            import sqlfun.operations
            from django.db import migrations


            class Migration(migrations.Migration):
                dependencies = [('sqlfun', '0003_delete_sqlfundefinition')]
                operations = [
                    sqlfun.operations.CreateFunction(
                        name='routed_fn',
                        identity_arguments='a integer',
                        result_type='integer',
                        sql=(
                            'CREATE OR REPLACE FUNCTION routed_fn(a integer) '
                            'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
                        ),
                    ),
                ]
            '''),
    )
    try:
        from sqlfun.state import get_replayed_state
        assert get_replayed_state()['routed_fn'].app_label == 'sqlfun'
    finally:
        remove_test_migration('sqlfun', path)
