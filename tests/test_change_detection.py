import pytest
from django.core.management import call_command
from django.db import connection

from sqlfun import SqlFun
from sqlfun.models import SqlFunDefinition
from sqlfun.utils import (
    get_migration_operations,
    make_sqlfun_migrations,
    update_sqlfun_definition_model,
)

from .utils import function_exists


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
def test_body_only_change_emits_create_or_replace_without_drop():
    class BodyOnly(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION body_only_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    try:
        update_sqlfun_definition_model()
        BodyOnly.sql = BodyOnly.sql.replace('SELECT a;', 'SELECT a + 1;')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if 'body_only_fn' in str(op.sql)
        ]
        assert len(operations) == 1
        operation = operations[0]
        assert isinstance(operation.sql, str)
        assert operation.sql == BodyOnly.sql
        assert 'DROP FUNCTION' not in operation.sql.upper()
        assert isinstance(operation.reverse_sql, str)
        assert 'body_only_fn' in operation.reverse_sql
    finally:
        BodyOnly.deregister()


@pytest.mark.django_db
def test_signature_change_emits_targeted_drop_then_create():
    class SigChange(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION sig_change_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    try:
        update_sqlfun_definition_model()
        SigChange.sql = SigChange.sql.replace('a integer', 'a bigint')

        operations = [
            op for op in get_migration_operations().get('test_project', [])
            if 'sig_change_fn' in str(op.sql)
        ]
        assert len(operations) == 1
        operation = operations[0]
        assert operation.sql[0] == 'DROP FUNCTION IF EXISTS sig_change_fn(a integer);'
        assert operation.sql[1] == SigChange.sql
        assert operation.reverse_sql[0] == 'DROP FUNCTION IF EXISTS sig_change_fn(a bigint);'
        assert 'CREATE OR REPLACE FUNCTION' in operation.reverse_sql[1].upper()
    finally:
        SigChange.deregister()


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
def test_deleted_function_drop_is_signature_aware_and_reversible():
    class ToDelete(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION to_delete_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    update_sqlfun_definition_model()
    ToDelete.deregister()

    operations = [
        op for op in get_migration_operations().get('test_project', [])
        if 'to_delete_fn' in str(op.sql)
    ]
    assert len(operations) == 1
    operation = operations[0]
    assert operation.sql == 'DROP FUNCTION IF EXISTS to_delete_fn(a integer);'
    assert 'CREATE OR REPLACE FUNCTION' in operation.reverse_sql.upper()


@pytest.mark.django_db
def test_old_format_stored_name_is_not_treated_as_deleted():
    """Regression test for the pre-branch regex, which preserved case and
    truncated schema-qualified names down to just the schema. A stored
    SqlFunDefinition row with such a raw ``function_name`` must still be
    recognized as matching an unchanged, currently-registered class -- it
    must not be classified as both new (via current_sql != previous_sql
    string mismatch is not the trigger here; the parsed-name comparison is)
    and deleted, which would otherwise emit a DROP that runs after CREATE.
    """

    class OldFormat(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION old_format_fn(a integer)
            RETURNS integer as $$
            SELECT a;
            $$ LANGUAGE sql IMMUTABLE;
        """

    try:
        update_sqlfun_definition_model()

        # Simulate a row written by the pre-branch regex: case preserved,
        # schema-qualified names truncated to just the schema.
        stored = SqlFunDefinition.objects.get(function_name='old_format_fn')
        stored.function_name = 'OLD_FORMAT_FN'
        stored.save()

        drop_ops = [
            op for op in get_migration_operations().get('test_project', [])
            if 'old_format_fn' in str(op.sql) and 'DROP FUNCTION' in str(op.sql).upper()
        ]
        assert drop_ops == []
    finally:
        OldFormat.deregister()
