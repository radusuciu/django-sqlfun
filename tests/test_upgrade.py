import textwrap

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.state import ProjectState

from sqlfun import SqlFun
from sqlfun.operations import CreateFunction
from sqlfun.utils import get_migration_operations, make_sqlfun_migrations

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
        'test_project',
        '0951_old_style_runsql',
        textwrap.dedent(f"""\
            from django.db import migrations


            class Migration(migrations.Migration):
                dependencies = [('test_project', '0001_initial')]
                operations = [
                    migrations.RunSQL(
                        sql={UPGRADE_SQL!r},
                        reverse_sql='DROP FUNCTION IF EXISTS upgrade_fn(integer);',
                    ),
                ]
            """),
    )
    try:
        call_command('migrate')
        assert function_exists('upgrade_fn')

        operations = [
            op
            for op in get_migration_operations().get('test_project', [])
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
            'INSERT INTO sqlfun_sqlfundefinition '
            '(function_name, sql_definition, app_label, identity_arguments, result_type) '
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
        'sqlfun',
        '0952_routing_probe',
        textwrap.dedent("""\
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
            """),
    )
    try:
        from sqlfun.state import get_replayed_state

        assert get_replayed_state()['routed_fn'].app_label == 'sqlfun'
    finally:
        remove_test_migration('sqlfun', path)


INCOMPATIBLE_V1_SQL = (
    'CREATE OR REPLACE FUNCTION upgrade_retyped_fn(a integer) RETURNS integer '
    'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
)


@pytest.mark.django_db
def test_runsql_history_with_incompatible_edit_drops_the_live_function():
    """The upgrade path where the class was edited to a new signature before
    the baseline makemigrations: replayed state knows nothing about the
    function, so the migration itself must drop the live one or CREATE OR
    REPLACE is rejected."""

    class Retyped(SqlFun):
        app_label = 'test_project'
        sql = (
            'CREATE OR REPLACE FUNCTION upgrade_retyped_fn(a integer, b integer) '
            'RETURNS bigint AS $$ SELECT (a + b)::bigint; $$ LANGUAGE sql IMMUTABLE;'
        )

    old_style = write_test_migration(
        'test_project',
        '0953_old_style_retyped',
        textwrap.dedent(f"""\
            from django.db import migrations


            class Migration(migrations.Migration):
                dependencies = [('test_project', '0001_initial')]
                operations = [
                    migrations.RunSQL(
                        sql={INCOMPATIBLE_V1_SQL!r},
                        reverse_sql='DROP FUNCTION IF EXISTS upgrade_retyped_fn(integer);',
                    ),
                ]
            """),
    )
    migration_paths = []
    try:
        call_command('migrate')
        baseline_target = '0953_old_style_retyped'

        migration_paths = make_sqlfun_migrations('upgrade_retyped')
        call_command('migrate')

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT pg_get_function_identity_arguments(p.oid), '
                'pg_get_function_result(p.oid) FROM pg_proc p '
                "WHERE p.proname = 'upgrade_retyped_fn'"
            )
            assert cursor.fetchall() == [('a integer, b integer', 'bigint')]
            cursor.execute('SELECT upgrade_retyped_fn(1, 2)')
            assert cursor.fetchone()[0] == 3

        # the generated migration is now the record: nothing further pending
        assert not any(
            getattr(op, 'name', None) == 'upgrade_retyped_fn'
            for op in get_migration_operations().get('test_project', [])
        )

        # reversing restores the function the RunSQL history created
        call_command('migrate', 'test_project', baseline_target)
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT pg_get_function_identity_arguments(p.oid), '
                'pg_get_function_result(p.oid) FROM pg_proc p '
                "WHERE p.proname = 'upgrade_retyped_fn'"
            )
            assert cursor.fetchall() == [('a integer', 'integer')]
    finally:
        Retyped.deregister()
        for path in migration_paths:
            path.unlink(missing_ok=True)
        remove_test_migration('test_project', old_style)


MOVED_V1_SQL = (
    'CREATE OR REPLACE FUNCTION moved_between_apps_fn(a integer) '
    'RETURNS integer AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;'
)


@pytest.mark.django_db
def test_function_moved_between_apps_depends_on_its_history():
    """zoo sorts after test_project, so without an explicit dependency both
    replay and migrate would run zoo's old definition last."""
    history = write_test_migration(
        'zoo',
        '0001_moved_fn_history',
        textwrap.dedent(f"""\
            import sqlfun.operations
            from django.db import migrations


            class Migration(migrations.Migration):
                dependencies = []
                operations = [
                    sqlfun.operations.CreateFunction(
                        name='moved_between_apps_fn',
                        identity_arguments='a integer',
                        result_type='integer',
                        sql={MOVED_V1_SQL!r},
                    ),
                ]
            """),
    )

    class Moved(SqlFun):
        app_label = 'test_project'
        sql = MOVED_V1_SQL.replace('SELECT a;', 'SELECT a + 1;')

    migration_paths = []
    try:
        migration_paths = make_sqlfun_migrations('moved_from_zoo')
        (written,) = migration_paths
        assert "('zoo', '0001_moved_fn_history')" in written.read_text()

        # the move is recorded: nothing further pending
        assert make_sqlfun_migrations('moved_again', is_dry_run=True) == []

        call_command('migrate')
        with connection.cursor() as cursor:
            cursor.execute('SELECT moved_between_apps_fn(1)')
            assert cursor.fetchone()[0] == 2
    finally:
        Moved.deregister()
        for path in migration_paths:
            remove_test_migration('test_project', path)
        remove_test_migration('zoo', history)
