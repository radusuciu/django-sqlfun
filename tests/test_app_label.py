import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from sqlfun import SqlFun
from sqlfun.naming import SqlFunError
from sqlfun.utils import get_migration_operations


@pytest.fixture
def label_free_probe():
    # classes defined in tests/*.py have no apps.py/models.py ancestor, so
    # get_app_label_for_cls returns None unless app_label is set
    class LabelFreeProbe(SqlFun):
        sql = """
            CREATE OR REPLACE FUNCTION label_free_probe(
                first integer
            ) RETURNS integer AS $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    yield LabelFreeProbe
    LabelFreeProbe.deregister()


@pytest.mark.django_db
def test_unresolvable_app_label_raises_with_class_name(label_free_probe):
    with pytest.raises(SqlFunError) as excinfo:
        get_migration_operations()
    assert 'LabelFreeProbe' in str(excinfo.value)
    assert 'app_label' in str(excinfo.value)


@pytest.mark.django_db
def test_unresolvable_app_label_fails_check_loudly(label_free_probe):
    with pytest.raises(CommandError, match='app_label'):
        call_command('makemigrations', '--check', stderr=io.StringIO())


@pytest.mark.django_db
def test_configuration_error_omits_signature_advice(label_free_probe):
    # a misconfigured app_label is not an unresolvable signature: telling the
    # user to run `migrate` and retry would send them down the wrong path
    with pytest.raises(CommandError) as excinfo:
        call_command('makemigrations', '--check', stderr=io.StringIO())
    assert 'Could not resolve a function signature' not in str(excinfo.value)


@pytest.fixture
def duplicate_identity_probes():
    # 'Dup_Fn' and 'dup_fn' normalize to the same identity; both would
    # otherwise silently collapse into a single registered entry.
    class DupFnUpper(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION Dup_Fn(
                first integer
            ) RETURNS integer AS $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    class DupFnLower(SqlFun):
        app_label = 'test_project'
        sql = """
            CREATE OR REPLACE FUNCTION dup_fn(
                first integer
            ) RETURNS integer AS $$
            SELECT first;
            $$ LANGUAGE sql IMMUTABLE;
        """

    yield DupFnUpper, DupFnLower
    DupFnUpper.deregister()
    DupFnLower.deregister()


@pytest.mark.django_db
def test_duplicate_identity_across_classes_raises_with_both_names(duplicate_identity_probes):
    with pytest.raises(SqlFunError) as excinfo:
        get_migration_operations()
    assert 'DupFnUpper' in str(excinfo.value)
    assert 'DupFnLower' in str(excinfo.value)
