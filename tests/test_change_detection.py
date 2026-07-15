import pytest
from django.core.management import call_command
from django.db import connection

from sqlfun import SqlFun
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
