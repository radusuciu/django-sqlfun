import pytest
from django.core.management import call_command
from django.db import connection

from sqlfun import SqlFun

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

    call_command('makemigrations')
    call_command('migrate')

    assert function_exists('first_of_two')

    with connection.cursor() as cursor:
        cursor.execute('SELECT first_of_two(1, 2)')
        assert cursor.fetchone()[0] == 1

    FirstOfTwo.sql = FirstOfTwo.sql.replace('SELECT first', 'SELECT second')

    call_command('makemigrations')
    call_command('migrate')

    with connection.cursor() as cursor:
        cursor.execute('SELECT first_of_two(1, 2)')
        assert cursor.fetchone()[0] == 2


@pytest.mark.django_db
def test_deleted_function():
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
    
    call_command('makemigrations')
    call_command('migrate')

    assert function_exists('first_of_two')

    FirstOfTwo.deregister()

    call_command('makemigrations')
    call_command('migrate')

    assert not function_exists('first_of_two')

    with connection.cursor() as cursor:
        with pytest.raises(Exception):
            cursor.execute('SELECT first_of_two(1, 2)')


@pytest.mark.django_db
def test_change_parameter_number():
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

    call_command('makemigrations')
    call_command('migrate')

    assert function_exists('first_of_two')

    FirstOfTwo.sql = FirstOfTwo.sql.replace('first integer', 'first integer, third integer')

    call_command('makemigrations')
    call_command('migrate')

    with connection.cursor() as cursor:
        cursor.execute('SELECT first_of_two(1, 2, 3)')
        assert cursor.fetchone()[0] == 1

        # test that exception is raised if we don't pass in the third parameter
        with pytest.raises(Exception):
            cursor.execute('SELECT first_of_two(1, 2, 3, 4)')
