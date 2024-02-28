import pytest
from django.core.management import call_command
from django.db import connection

from sqlfun import SqlFun
from sqlfun.utils import make_sqlfun_migrations

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

    with connection.cursor() as cursor:
        cursor.execute('SELECT first_of_two_change_parameter_number(1, 2, 3)')
        assert cursor.fetchone()[0] == 1

        # test that exception is raised if we don't pass in the third parameter
        with pytest.raises(Exception):
            cursor.execute('SELECT first_of_two_change_parameter_number(1, 2, 3, 4)')

    for path in migration_paths:
        path.unlink()
