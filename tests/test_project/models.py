from sqlfun import SqlFun

from django.db.models import IntegerField, Model


class Foo(Model):
    """A model for testing purposes."""
    foo = IntegerField()

    class Meta:
        app_label = 'test_project'


class BadSum(SqlFun):
    """Almost returns the sum of two numbers."""
    
    sql = """
        CREATE OR REPLACE FUNCTION bad_sum(
            first integer,
            second integer
        ) RETURNS integer as $$
        SELECT first + second + 1;
        $$
        LANGUAGE sql
        stable;
    """

    output_field = IntegerField()
