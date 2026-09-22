import pathlib
from io import StringIO
from unittest.mock import mock_open, patch

import pytest
from django.conf import settings
from django.core.management import call_command

from sqlfun import SqlFun
from sqlfun.utils import (
    generate_migration,
    make_sqlfun_migrations,
)

from .utils import function_exists


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
    # handle this differently with some mocking
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


@pytest.mark.django_db
def test_makemigrations_hard_fails_on_unintrospectable_sql():
    from django.core.management.base import CommandError

    class Unparseable(SqlFun):
        app_label = 'test_project'
        sql = 'CREATE OR REPLACE FUNCTION broken_fn RETURNS integer AS $$ SELECT 1; $$ LANGUAGE sql;'

    stderr = StringIO()
    try:
        with pytest.raises(CommandError, match='Unparseable'):
            call_command('makemigrations', 'test_project', '--dry-run', stderr=stderr)
    finally:
        Unparseable.deregister()


@pytest.mark.django_db
def test_signature_error_does_not_block_django_makemigrations():
    """A function whose signature references a type created by a still-
    pending model migration must not block Django's own makemigrations --
    otherwise the migration that would create the type can never be
    generated. The command runs Django's makemigrations first, then fails
    with a message pointing at migrate."""
    from django.core.management.base import CommandError
    from django.core.management.commands.makemigrations import (
        Command as DjangoMakeMigrations,
    )

    class NeedsPendingType(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION needs_pending_type_fn(a integer)
            RETURNS SETOF table_from_pending_migration as $$
            SELECT * FROM table_from_pending_migration;
            $$ LANGUAGE sql STABLE;
        """

    base_ran = []
    try:
        with patch.object(
            DjangoMakeMigrations,
            'handle',
            side_effect=lambda *a, **k: base_ran.append(True),
        ):
            with pytest.raises(CommandError, match='pending migration'):
                call_command('makemigrations')
        assert base_ran, 'Django makemigrations must run before sqlfun hard-fails'
    finally:
        NeedsPendingType.deregister()


@pytest.mark.django_db
def test_sqlfun_definition_has_signature_columns():
    from sqlfun.models import SqlFunDefinition
    row = SqlFunDefinition.objects.create(
        function_name='public.shape_probe',
        sql_definition='CREATE FUNCTION shape_probe() RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql;',
        app_label='test_project',
        identity_arguments='',
        result_type='integer',
    )
    row.refresh_from_db()
    assert row.identity_arguments == ''
    assert row.result_type == 'integer'


def test_error_aliases():
    from sqlfun import SqlFunError, SqlFunParseError
    assert SqlFunParseError is SqlFunError


def test_generate_migration_invalidates_import_caches():
    # freshly written base-command migrations must be visible to the loader;
    # without invalidate_caches a stale FileFinder can miss or fail to import
    # a just-written module
    calls = []
    with patch('sqlfun.utils.importlib.invalidate_caches', side_effect=lambda: calls.append(1)):
        with patch('sqlfun.utils.MigrationLoader') as loader_cls:
            loader_cls.return_value.graph.leaf_nodes.return_value = []
            generate_migration('0001_probe', 'test_project', [], is_dry_run=True)
    assert calls, 'invalidate_caches must run before MigrationLoader is built'
