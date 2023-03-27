[![PyPI version fury.io](https://img.shields.io/pypi/v/django-sqlfun.svg)](https://pypi.python.org/pypi/django-sqlfun/)
[![GitHub release](https://img.shields.io/github/release/radusuciu/django-sqlfun.svg)](https://github.com/radusuciu/django-sqlfun/releases/)

# Django SQL Fun

Django SQLFun allows you to define and manage custom SQL functions in code. When you change the function definitions and call `makemigrations`, it will generate migrations for any functions that have been added, removed, or changed. These function classes can also be used in Django querysets since the `SqlFun` class inherits from [`django.db.models.expressions.Func`](https://docs.djangoproject.com/en/3.2/ref/models/expressions/#func-expressions).

**Note**: I'm still developing this so there may be some rough edges. Breaking changes may happen.

## Installation and Use

1. Install using your favorite python package manager, eg. `pip install django-sqlfun`.
2. Add `sqlfun` to `INSTALLED_APPS` in your django settings.
3. Define a custom function in a module that gets imported on project load (eg. `models.py`). See below for example, or the [`test_project`](tests/test_project).
4. Run `manage.py makemigrations` and then `manage.py migrate`.

### Example

Define a custom function in your `models.py`:

```python
# models.py
from sqlfun import SqlFun
from django.db.models import IntegerField

class BadSum(SqlFun):
    """Almost returns the sum of two numbers."""
    
    app_label = 'test_project' # [optional] if omitted, sqlfun will atempt to auto-resolve it
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
```

Then run `manage.py makemigrations` and `manage.py migrate` and you should be good to go. You can use it in SQL: `SELECT bad_sum(2, 2)`, or in a Python queryset like so: `MyModel.objects.annotate(foo=BadSum(Value(2), Value(2)))`.

### Notes

- SQL functions are normalized, so changes in white-space should not result in changes being detected
- the `--dry-run` and `--name` options of `makemigrations` are respected

## Credits

This project is inspired by two great projects: [`django-pgtrigger`](https://github.com/Opus10/django-pgtrigger) and [`django-pgviews`](https://github.com/mypebble/django-pgviews).
