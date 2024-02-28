import pytest

from sqlfun.utils import make_sqlfun_migrations

from django.core.management import call_command
from test_project.models import BadSum, Foo


@pytest.mark.django_db
def test_bad_sum_with_queryset():
    migrations_paths = make_sqlfun_migrations()
    call_command('migrate')
    Foo.objects.create(foo=3)
    annotated_queryset = Foo.objects.annotate(bad_sum_result=BadSum(3, 5))
    result = annotated_queryset.first()
    assert result.bad_sum_result == 3 + 5 + 1
    for path in migrations_paths:
        path.unlink()
