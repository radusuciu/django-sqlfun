import pathlib
from unittest.mock import mock_open, patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection

from sqlfun import SqlFun
from sqlfun.utils import (
    generate_migration,
    make_sqlfun_migrations,
)


def function_exists(function_name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM information_schema.routines WHERE routine_name = %s', [function_name])
        return cursor.fetchone()[0] == 1


@pytest.mark.django_db
def test_migrate():
    assert not function_exists('first_of_two')

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
            stable;
        """

    assert FirstOfTwo in SqlFun._registry

    # not using call_command('makemigrations') because we need
    # the paths so we can clean them up.. though we could maybe
    # handle this differently
    migration_paths = make_sqlfun_migrations()
    assert len(migration_paths) == 1

    call_command('migrate')
    assert function_exists('first_of_two')

    for path in migration_paths:
        path.unlink()


def test_generate_migration_write():
    migration_name = 'test_migration_001'
    app_label = 'myapp'
    operations = []

    with patch('pathlib.Path.open', mock_open()) as mock_file:
        migration_path = generate_migration(
            migration_name,
            app_label,
            operations,
        )
        expected_path = pathlib.Path(settings.BASE_DIR) / app_label / 'migrations' / f'{migration_name}.py'
        assert migration_path == expected_path
        mock_file.assert_called_once()
        mock_file.assert_called_with('w')

    with patch('pathlib.Path.open', mock_open()) as mock_file:
        migration_path = generate_migration(
            migration_name,
            app_label,
            operations,
            is_dry_run=True,
        )
        assert migration_path == expected_path
        mock_file.assert_not_called()
