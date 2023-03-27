import pytest

from test_project.models import BadSum, Foo


@pytest.mark.django_db
def test_bad_sum_with_queryset():
    Foo.objects.create(foo=3)
    annotated_queryset = Foo.objects.annotate(bad_sum_result=BadSum(3, 5))
    result = annotated_queryset.first()
    assert result.bad_sum_result == 3 + 5 + 1