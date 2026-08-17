import io
import pathlib
from unittest.mock import patch

import django
import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.management.commands.makemigrations import Command as DjangoMakeMigrations

from sqlfun import SqlFun
from sqlfun.models import SqlFunDefinition
from sqlfun.utils import make_sqlfun_migrations

MIGRATIONS_DIR = pathlib.Path(settings.BASE_DIR) / 'test_project' / 'migrations'


@pytest.mark.django_db
def test_check_exits_nonzero_and_writes_nothing_for_pending_sqlfun_changes():
    # sync everything currently registered so CheckProbe below is the only
    # pending change (the tracking table starts empty in every test)
    baseline_paths = make_sqlfun_migrations('check_baseline')

    class CheckProbe(SqlFun):
        """Function used only by this test."""
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION check_probe(
                first integer
            ) RETURNS integer as $$
            SELECT first;
            $$
            LANGUAGE sql
            IMMUTABLE;
        """

    written_paths = []
    try:
        files_before = set(MIGRATIONS_DIR.glob('*.py'))

        stderr = io.StringIO()
        with pytest.raises(SystemExit) as excinfo:
            call_command('makemigrations', '--check', stderr=stderr)
        assert excinfo.value.code == 1
        assert 'sqlfun function changes are missing migrations' in stderr.getvalue()

        # --check wrote no migration files
        assert set(MIGRATIONS_DIR.glob('*.py')) == files_before
        # --check did not sync the tracking table
        assert not SqlFunDefinition.objects.filter(function_name='check_probe').exists()

        # detection survived: a real run still generates the migration
        written_paths = make_sqlfun_migrations('after_check')
        assert len(written_paths) == 1
        assert written_paths[0].exists()
    finally:
        CheckProbe.deregister()
        for path in written_paths:
            path.unlink(missing_ok=True)
        for path in baseline_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_check_passes_when_no_pending_changes():
    baseline_paths = make_sqlfun_migrations('check_clean_baseline')
    try:
        # must complete without SystemExit: no model changes, no sqlfun changes
        call_command('makemigrations', '--check')
    finally:
        for path in baseline_paths:
            path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_check_honors_positional_app_labels():
    # the pending sqlfun change lives in test_project; asking about only the
    # sqlfun app must not fail --check, asking about test_project must
    call_command('makemigrations', 'sqlfun', '--check')

    with pytest.raises(SystemExit) as excinfo:
        call_command('makemigrations', 'test_project', '--check')
    assert excinfo.value.code == 1


@pytest.mark.django_db
def test_check_reports_sqlfun_changes_even_when_django_exits_on_model_changes():
    # when model changes are also pending, Django's own handle() calls
    # sys.exit(1) and never returns — the sqlfun explanation must already
    # be on stderr by then
    stderr = io.StringIO()
    with patch.object(DjangoMakeMigrations, 'handle', side_effect=SystemExit(1)):
        with pytest.raises(SystemExit) as excinfo:
            call_command('makemigrations', '--check', stderr=stderr)
    assert excinfo.value.code == 1
    assert 'sqlfun function changes are missing migrations' in stderr.getvalue()


@pytest.mark.django_db
def test_check_fails_loudly_when_sqlfun_evaluation_fails():
    with patch(
        'sqlfun.management.commands.makemigrations.make_sqlfun_migrations',
        side_effect=Exception('boom'),
    ):
        with pytest.raises(CommandError):
            call_command('makemigrations', '--check')


@pytest.mark.django_db
def test_check_fails_loudly_when_sqlfun_table_is_missing():
    with patch(
        'sqlfun.management.commands.makemigrations.make_sqlfun_migrations',
        side_effect=django.db.utils.ProgrammingError('relation does not exist'),
    ):
        with pytest.raises(CommandError, match='SqlFunDefinition'):
            call_command('makemigrations', '--check')


@pytest.mark.django_db
def test_without_check_evaluation_failure_still_warns_and_continues():
    stderr = io.StringIO()
    with patch(
        'sqlfun.management.commands.makemigrations.make_sqlfun_migrations',
        side_effect=Exception('boom'),
    ):
        # must not raise: warn-and-continue behavior is preserved off --check
        call_command('makemigrations', '--dry-run', stderr=stderr)
    assert 'Could not make migrations for sqlfun functions' in stderr.getvalue()
