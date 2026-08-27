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
    with pytest.raises(CommandError):
        call_command('makemigrations', '--check', stderr=io.StringIO())
