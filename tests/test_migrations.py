import pathlib
from io import StringIO
from unittest.mock import DEFAULT, mock_open, patch

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command

from sqlfun import SqlFun
from sqlfun.naming import SqlFunError
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

    try:
        # not using call_command('makemigrations') because we need
        # the paths so we can clean them up.. though we could maybe
        # handle this differently with some mocking
        migration_paths = make_sqlfun_migrations()
        assert len(migration_paths) == 1

        call_command('migrate')
        assert function_exists('first_of_two')

        for path in migration_paths:
            path.unlink()
    finally:
        FirstOfTwo.deregister()


def test_generate_migration_write():
    migration_name = 'test_migration_001'
    app_label = 'test_project'
    operations = []

    with patch('pathlib.Path.open', mock_open()) as mock_file:
        migration_path = generate_migration(
            migration_name,
            app_label,
            operations,
        )
        expected_path = pathlib.Path(
            django_apps.get_app_config(app_label).path) / 'migrations' / f'{migration_name}.py'
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


def test_make_sqlfun_migrations_invalidates_caches_before_shared_loader():
    # the production path builds one loader for the whole run; it must be
    # constructed after the caches are invalidated or it can miss migrations
    # the base makemigrations just wrote
    events = []
    with patch(
        'sqlfun.utils.importlib.invalidate_caches',
        side_effect=lambda: events.append('invalidate'),
    ):
        with patch('sqlfun.utils.MigrationLoader') as loader_cls:
            def build_loader(*args, **kwargs):
                events.append('loader')
                return DEFAULT

            loader_cls.side_effect = build_loader
            with patch(
                'sqlfun.utils.get_migration_operations', return_value={},
            ) as get_operations:
                make_sqlfun_migrations(is_dry_run=True)
    assert events == ['invalidate', 'loader']
    assert get_operations.call_args.kwargs['loader'] is loader_cls.return_value


@pytest.mark.django_db
def test_migration_written_to_app_config_path_not_base_dir(tmp_path, settings):
    # BASE_DIR is a guess; the loader reads back via app_config.path — the
    # two must be the same place or change detection never sees the file
    settings.BASE_DIR = tmp_path
    path = generate_migration('0999_path_probe', 'test_project', [], is_dry_run=True)
    expected_dir = pathlib.Path(
        django_apps.get_app_config('test_project').path) / 'migrations'
    assert path.parent == expected_dir
    assert not (tmp_path / 'test_project').exists()


def test_unknown_app_label_raises():
    with pytest.raises(SqlFunError) as excinfo:
        generate_migration('0999_nope', 'not_installed_app', [], is_dry_run=True)
    assert 'not_installed_app' in str(excinfo.value)


def test_sqlfun_app_refused_as_migration_target():
    with pytest.raises(SqlFunError) as excinfo:
        generate_migration('0999_nope', 'sqlfun', [], is_dry_run=True)
    assert 'hand-write' in str(excinfo.value)
