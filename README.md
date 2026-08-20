[![PyPI pyversions](https://img.shields.io/pypi/pyversions/django-sqlfun.svg)](https://pypi.python.org/pypi/django-sqlfun/)
[![Django versions](https://img.shields.io/pypi/frameworkversions/django/django-sqlfun)](https://pypi.python.org/pypi/django-sqlfun/)
[![PyPI version](https://img.shields.io/pypi/v/django-sqlfun.svg)](https://pypi.python.org/pypi/django-sqlfun/)
[![GitHub release](https://img.shields.io/github/release/radusuciu/django-sqlfun.svg)](https://github.com/radusuciu/django-sqlfun/releases/)

# Django SQL Fun

Django SQLFun allows you to define and manage custom SQL functions in code. When you change the function definitions and call `makemigrations`, it will generate migrations for any functions that have been added, removed, or changed. These function classes can also be used in Django querysets since the `SqlFun` class inherits from [`django.db.models.expressions.Func`](https://docs.djangoproject.com/en/5.0/ref/models/expressions/#func-expressions).

**Note**: I'm still developing this so there may be some rough edges. Breaking changes may happen.

## Installation

1. Install using your favorite python package manager, eg. `pip install django-sqlfun`.
2. Add `sqlfun` to `INSTALLED_APPS` in your django settings
3. Run `manage.py migrate` (on a fresh install this is a no-op for sqlfun; on upgrades from ≤0.1.x it removes sqlfun's old bookkeeping table)

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

- Function definitions must use `CREATE OR REPLACE FUNCTION` — `makemigrations` rejects plain `CREATE FUNCTION`, since sqlfun re-executes definitions against databases where the function may already exist
- SQL functions are normalized before comparison, so whitespace-only changes do not generate migrations
- Change detection works by replaying sqlfun's operations from your existing migration files — there is no state outside your repo, so fresh clones and CI see exactly what you see
- If you squash or delete migrations that contain sqlfun operations, that state is lost: the next `makemigrations` re-emits a baseline migration re-declaring the affected functions (harmless to apply, but noisy)
- the `--dry-run`, `--name`, and `--check` options of `makemigrations` are respected. `--check` exits with a non-zero status if any sqlfun function changes are missing migrations (in addition to Django's own model-change check), writes nothing, and requires a reachable database — it fails rather than silently passing if sqlfun changes cannot be evaluated.

### Upgrading

**From ≤0.1.x to 0.2.0** (breaking): sqlfun no longer keeps a bookkeeping
table — a function's history now lives in your migration files as
`sqlfun.operations.CreateFunction` / `DropFunction` operations. To upgrade
an existing project:

1. Upgrade the package.
2. Run `manage.py migrate` — this drops sqlfun's old tracking table.
3. Run `manage.py makemigrations` once, **before editing or deleting any
   function definitions**. Your old migrations contain only `RunSQL`
   operations, which the new change detection does not read, so this run
   emits one baseline migration per app re-declaring every registered
   function.
4. Run `manage.py migrate` — the baseline applies as a no-op
   `CREATE OR REPLACE` against your existing functions.

If you deleted a function class before step 3, sqlfun has no record of it:
drop that function manually.

Moving a `SqlFun` class between apps is not supported cleanly: each
function's operation history should stay in one app's migrations. If a
class moves apps, replayed state can pin the old app's definition and
`makemigrations` may re-emit the same migration repeatedly — keep the
function's history in its original app, or hand-write a migration moving
it.

Reversing the post-upgrade baseline migration drops the function outright,
since the baseline carries no previous definition — even though on an
upgraded install the function predates it. Treat the baseline as
forward-only.

## Development

These instructions assume a recent Ubuntu/Debian environment.

1. Clone the repository
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
3. Install the `libpq-dev` package since `psycopg2` depends on it.
4. Install dependencies with `uv sync` (this creates `.venv` and installs the dev group)

Testing also requires a recent install of docker which is used to spin up a test postgres instance.

## Credits

This project is inspired by two great projects: [`django-pgtrigger`](https://github.com/Opus10/django-pgtrigger) and [`django-pgviews`](https://github.com/mypebble/django-pgviews).
