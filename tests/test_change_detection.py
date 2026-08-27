import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from sqlfun import SqlFun
from sqlfun.operations import CreateFunction, DropFunction
from sqlfun.utils import get_migration_operations, make_sqlfun_migrations

from .utils import function_exists, remove_test_migration


@pytest.mark.django_db
def test_changed_function_body():

    class FirstOfTwo(SqlFun):
        """Returns the sum of two numbers plus one."""
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION first_of_two(
                first integer,
                second integer
            ) RETURNS integer as $$
            SELECT first;
            $$
            LANGUAGE sql
            IMMUTABLE;
        """

    try:
        migration_paths = make_sqlfun_migrations('changed_body')
        call_command('migrate')

        assert function_exists('first_of_two')

        with connection.cursor() as cursor:
            cursor.execute('SELECT first_of_two(1, 2)')
            assert cursor.fetchone()[0] == 1

        FirstOfTwo.sql = FirstOfTwo.sql.replace('SELECT first', 'SELECT second')

        migration_paths.extend(make_sqlfun_migrations('changed_body'))
        call_command('migrate')

        with connection.cursor() as cursor:
            cursor.execute('SELECT first_of_two(1, 2)')
            assert cursor.fetchone()[0] == 2

        for path in migration_paths:
            path.unlink()
    finally:
        FirstOfTwo.deregister()


@pytest.mark.django_db
def test_deleted_function():
    class FirstOfTwo(SqlFun):
        """Returns the sum of two numbers plus one."""
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION first_of_two_deleted(
                first integer,
                second integer
            ) RETURNS integer as $$
            SELECT first;
            $$
            LANGUAGE sql
            IMMUTABLE;
        """

    migrations_paths = make_sqlfun_migrations('deleted_function')
    call_command('migrate')

    assert function_exists('first_of_two_deleted')

    FirstOfTwo.deregister()

    migrations_paths.extend(make_sqlfun_migrations('deleted_function'))
    call_command('migrate')

    assert not function_exists('first_of_two_deleted')

    with connection.cursor() as cursor:
        with pytest.raises(Exception):
            cursor.execute('SELECT first_of_two_deleted(1, 2)')

    for path in migrations_paths:
        path.unlink()


@pytest.mark.django_db
def test_change_parameter_number():
    class FirstOfTwo(SqlFun):
        """Returns the sum of two numbers plus one."""
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION first_of_two_change_parameter_number(
                first integer,
                second integer
            ) RETURNS integer as $$
            SELECT first;
            $$
            LANGUAGE sql
            IMMUTABLE;
        """

    migration_paths = make_sqlfun_migrations('change_parameter_number')
    call_command('migrate')

    assert function_exists('first_of_two_change_parameter_number')

    FirstOfTwo.sql = FirstOfTwo.sql.replace('first integer', 'first integer, third integer')

    migration_paths.extend(make_sqlfun_migrations('change_parameter_number'))
    call_command('migrate')

    # function_exists counts routines by name, so it is only true when
    # exactly one overload exists -- the old 2-arg overload must be gone
    assert function_exists('first_of_two_change_parameter_number')

    with connection.cursor() as cursor:
        cursor.execute('SELECT first_of_two_change_parameter_number(1, 2, 3)')
        assert cursor.fetchone()[0] == 1

    # the old 2-arg signature must no longer be callable
    with pytest.raises(Exception):
        with connection.cursor() as cursor:
            cursor.execute('SELECT first_of_two_change_parameter_number(1, 2)')

    for path in migration_paths:
        path.unlink()


@pytest.mark.django_db
def test_body_only_change_emits_create_without_incompatible_signature():
    class BodyOnly(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION body_only_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seed_paths = []
    try:
        seed_paths = make_sqlfun_migrations('seed_body_only')
        BodyOnly.sql = BodyOnly.sql.replace('SELECT a;', 'SELECT a + 1;')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'body_only_fn'
        ]
        assert len(operations) == 1
        operation = operations[0]
        assert isinstance(operation, CreateFunction)
        assert operation.previous_sql is not None
        assert operation.previous_identity_arguments == operation.identity_arguments
        assert operation.previous_result_type == operation.result_type
    finally:
        BodyOnly.deregister()
        for path in seed_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_signature_change_carries_previous_signature():
    class SigChange(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION sig_change_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seed_paths = []
    try:
        seed_paths = make_sqlfun_migrations('seed_sig_change')
        SigChange.sql = SigChange.sql.replace('a integer', 'a bigint')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'sig_change_fn'
        ]
        assert len(operations) == 1
        operation = operations[0]
        assert isinstance(operation, CreateFunction)
        assert operation.identity_arguments == 'a bigint'
        assert operation.previous_identity_arguments == 'a integer'
        assert 'CREATE OR REPLACE FUNCTION' in operation.previous_sql.upper()
    finally:
        SigChange.deregister()
        for path in seed_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_change_return_type():
    class ReturnsInt(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION change_return_type_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    migration_paths = []
    try:
        migration_paths = make_sqlfun_migrations('change_return_type')
        call_command('migrate')
        assert function_exists('change_return_type_fn')

        ReturnsInt.sql = ReturnsInt.sql.replace('RETURNS integer', 'RETURNS bigint')
        migration_paths.extend(make_sqlfun_migrations('change_return_type_2'))
        # before this fix, plain CREATE OR REPLACE would fail here with
        # "cannot change return type of existing function"
        call_command('migrate')

        assert function_exists('change_return_type_fn')
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_typeof(change_return_type_fn(1))::text")
            assert cursor.fetchone()[0] == 'bigint'
    finally:
        ReturnsInt.deregister()
        for path in migration_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_rename_parameter():
    class Renamed(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION rename_param_fn(first integer)
            RETURNS integer as $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    migration_paths = []
    try:
        migration_paths = make_sqlfun_migrations('rename_param')
        call_command('migrate')

        Renamed.sql = """
            CREATE OR REPLACE FUNCTION rename_param_fn(initial integer)
            RETURNS integer as $$
            SELECT initial;
            $$ LANGUAGE sql IMMUTABLE;
        """
        migration_paths.extend(make_sqlfun_migrations('rename_param_2'))
        # before this fix, plain CREATE OR REPLACE would fail here with
        # "cannot change name of input parameter"
        call_command('migrate')

        assert function_exists('rename_param_fn')
        with connection.cursor() as cursor:
            cursor.execute('SELECT rename_param_fn(initial := 7)')
            assert cursor.fetchone()[0] == 7
    finally:
        Renamed.deregister()
        for path in migration_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_reverse_signature_change_restores_old_signature():
    class Reversible(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION reverse_sig_fn(first integer, second integer)
            RETURNS integer as $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    migration_paths = []
    try:
        migration_paths = make_sqlfun_migrations('reverse_sig_v1')
        call_command('migrate')
        forward_target = migration_paths[0].stem

        Reversible.sql = Reversible.sql.replace('first integer,', 'first bigint,')
        migration_paths.extend(make_sqlfun_migrations('reverse_sig_v2'))
        call_command('migrate')

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_function_identity_arguments('reverse_sig_fn'::regproc)"
            )
            assert cursor.fetchone()[0] == 'first bigint, second integer'

        call_command('migrate', 'test_project', forward_target)

        assert function_exists('reverse_sig_fn')
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_function_identity_arguments('reverse_sig_fn'::regproc)"
            )
            assert cursor.fetchone()[0] == 'first integer, second integer'
    finally:
        Reversible.deregister()
        for path in migration_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_deleted_function_emits_drop_with_stored_definition():
    class ToDelete(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION to_delete_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seed_paths = []
    try:
        seed_paths = make_sqlfun_migrations('seed_to_delete')
        ToDelete.deregister()

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'to_delete_fn'
        ]
        assert len(operations) == 1
        operation = operations[0]
        assert isinstance(operation, DropFunction)
        assert operation.identity_arguments == 'a integer'
        assert 'CREATE OR REPLACE FUNCTION' in operation.sql.upper()
    finally:
        for path in seed_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_type_alias_respelling_is_not_a_signature_change():
    class Aliased(SqlFun):
        app_label = 'test_project'
        sql = ('CREATE OR REPLACE FUNCTION alias_fn(a int) RETURNS int '
               'AS $$ SELECT a; $$ LANGUAGE sql IMMUTABLE;')

    seed_paths = []
    try:
        seed_paths = make_sqlfun_migrations('seed_alias')
        Aliased.sql = Aliased.sql.replace('a int', 'a integer').replace(
            'RETURNS int', 'RETURNS integer')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'alias_fn'
        ]
        # the SQL text changed, so an operation is emitted -- but both
        # spellings introspect to identical identity arguments, so it must
        # not take the drop-first path
        assert len(operations) == 1
        operation = operations[0]
        assert isinstance(operation, CreateFunction)
        assert operation.previous_identity_arguments == operation.identity_arguments
        assert operation.previous_result_type == operation.result_type
    finally:
        Aliased.deregister()
        for path in seed_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_out_param_function_generates_migration():
    class Totals(SqlFun):
        app_label = 'test_project'
        sql = ('CREATE OR REPLACE FUNCTION totals_fn(IN a integer, OUT s integer, OUT p integer) '
               'AS $$ SELECT a, a; $$ LANGUAGE sql;')

    migration_paths = []
    try:
        migration_paths = make_sqlfun_migrations('out_params')
        call_command('migrate')
        assert function_exists('totals_fn')
    finally:
        Totals.deregister()
        for path in migration_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_unchanged_function_emits_no_operations():
    class Unchanged(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION unchanged_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seed_paths = []
    try:
        seed_paths = make_sqlfun_migrations('seed_unchanged')
        # the migration stores raw SQL; comparison must re-normalize both
        # sides, so an untouched definition yields nothing
        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'unchanged_fn'
        ]
        assert operations == []
    finally:
        Unchanged.deregister()
        for path in seed_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_whitespace_only_change_emits_no_operations():
    class Whitespaced(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION whitespace_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    seed_paths = []
    try:
        seed_paths = make_sqlfun_migrations('seed_whitespace')
        Whitespaced.sql = Whitespaced.sql.replace('\n', '\n    ')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if getattr(op, 'name', None) == 'whitespace_fn'
        ]
        assert operations == []
    finally:
        Whitespaced.deregister()
        for path in seed_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_dry_run_does_not_consume_detection():
    class DryRunProbe(SqlFun):
        """Function used only by this test."""
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION dry_run_probe(
                first integer
            ) RETURNS integer as $$
            SELECT first;
            $$
            LANGUAGE sql
            IMMUTABLE;
        """

    written_paths = []
    try:
        dry_paths = make_sqlfun_migrations('dry_run_probe', is_dry_run=True)
        assert len(dry_paths) == 1
        assert not dry_paths[0].exists()

        # a dry run writes no migration file, so a subsequent real run
        # must still detect the pending change and write the migration
        written_paths = make_sqlfun_migrations('dry_run_probe')
        assert len(written_paths) == 1
        assert written_paths[0].exists()
    finally:
        DryRunProbe.deregister()
        for path in written_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_filtered_noop_run_does_not_consume_other_apps_detection():
    """Filtering to an app with no operations must not consume another
    app's pending detection."""

    class FilteredProbe(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION filtered_probe_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    written_paths = []
    try:
        assert make_sqlfun_migrations('filtered', app_labels=['sqlfun']) == []

        written_paths = make_sqlfun_migrations('after_filtered')
        assert len(written_paths) == 1
    finally:
        FilteredProbe.deregister()
        for path in written_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_identity_is_search_path_independent():
    # the worktree scenario: two dev environments with different search_path
    # values must produce byte-identical migration operations
    class WtProbe(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION wt_probe(
                first integer
            ) RETURNS integer AS $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    def operations_with_search_path(schema):
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS {schema}')
            cursor.execute(f'SET search_path TO {schema}, public')
        try:
            return get_migration_operations()
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SET search_path TO "$user", public')

    try:
        ops_a = operations_with_search_path('wt_a')
        ops_b = operations_with_search_path('wt_b')
        # test_project also permanently registers BadSum (see
        # tests/test_project/models.py), so filter down to the probe
        op_a, = [op for op in ops_a['test_project'] if 'wt_probe' in op.name]
        op_b, = [op for op in ops_b['test_project'] if 'wt_probe' in op.name]
        assert op_a.name == 'wt_probe'   # unqualified, no baked-in schema
        assert op_a.deconstruct() == op_b.deconstruct()
    finally:
        WtProbe.deregister()


@pytest.mark.django_db
def test_unchanged_functions_trigger_no_database_queries():
    class SteadyProbe(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION steady_probe(
                first integer
            ) RETURNS integer AS $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    written_paths = make_sqlfun_migrations('steady_baseline')
    try:
        with CaptureQueriesContext(connection) as ctx:
            operations = get_migration_operations()
        assert operations == {}
        assert len(ctx.captured_queries) == 0, ctx.captured_queries
    finally:
        SteadyProbe.deregister()
        for path in written_paths:
            remove_test_migration('test_project', path)
