[![PyPI pyversions](https://img.shields.io/pypi/pyversions/django-sqlfun.svg)](https://pypi.python.org/pypi/django-sqlfun/)
[![Django versions](https://img.shields.io/pypi/frameworkversions/django/django-sqlfun)](https://pypi.python.org/pypi/django-sqlfun/)
[![PyPI version](https://img.shields.io/pypi/v/django-sqlfun.svg)](https://pypi.python.org/pypi/django-sqlfun/)
[![GitHub release](https://img.shields.io/github/release/radusuciu/django-sqlfun.svg)](https://github.com/radusuciu/django-sqlfun/releases/)

# Django SQL Fun

Django SQLFun allows you to define and manage custom SQL functions in code. When you change the function definitions and call `makemigrations`, it will generate migrations for any functions that have been added, removed, or changed. These function classes can also be used in Django querysets since the `SqlFun` class inherits from [`django.db.models.expressions.Func`](https://docs.djangoproject.com/en/3.2/ref/models/expressions/#func-expressions).

**Note**: I'm still developing this so there may be some rough edges. Breaking changes may happen.

## Installation

1. Install using your favorite python package manager, eg. `pip install django-sqlfun`.
2. Add `sqlfun` to `INSTALLED_APPS` in your django settings
3. Run `manage.py migrate`. This will set up any tables required by `sqlfun` to keep track of your custom funcitons

## Use

1. Define a custom function in a module that gets imported on project load (eg. `models.py`). See below for example, or the [`test_project`](tests/test_project).
2. Run `manage.py makemigrations`
3. Run `manage.py migrate`

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

## Development

These instructions assume a recent Ubuntu/Debian environment.

1. Clone the repository
2. If needed, install `python3-venv` and `python3-pip` packages
3. Create a virtual environment `python3 -m venv .venv`
4. Install `libpq-dev` package since `psycopg2` depends on it.
5. Install `pdm`: `pip3 install --user pdm`
6. Install dev dependencies with `pdm install --dev`

Testing also requires a recent install of docker which is used to spin up a test postgres instance.

## Credits

This project is inspired by two great projects: [`django-pgtrigger`](https://github.com/Opus10/django-pgtrigger) and [`django-pgviews`](https://github.com/mypebble/django-pgviews).
