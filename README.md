# django-sqlfun

Django SQLFun allows you to define custom SQL functions in code which are then kept up to date in the database with every run of `manage.py migrate`.

## Use

1. Install using your favorite python package manager, eg. `pip install django-sqlfun`
2. Add `django_sqlfun` to `INSTALLED_APPS` in your django settings.
3. Define a custom function in a module that gets imported on project load (eg. `models.py`). See below for example.
4. Run `manage.py migrate`

### Example

```python
from django_sqlfun import SqlFun

class BadSum(SqlFun):
    ""Almost returns the sum of two numbers."""
    
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
```

## Planned Developments

This is **alpha** level software, and thus far only tested with Postgres.

- Add support for usage in Python code by inheriting from [`django.db.models.expressions.Func`](https://docs.djangoproject.com/en/3.2/ref/models/expressions/#func-expressions).
- Integrate into migrations system. Currently if you use functions that are defined through `django-sqlfun` in django migrations, you may experience errors since the latest version of that function will always be used. I believe this can be tackled with the [same approach used by the `django-pgtrigger` project](https://github.com/Opus10/django-pgtrigger/pull/66).
- Handle deleted custom functions. Currently if you delete a `django-sqlfun` function, it is not automatically deleted in the database itself. This could likely also be solved by integrating into the migrations system.

Ideas for improvement are welcome. Breaking changes are possible.

## Credits

This project is inspired by two great projects: [`django-pgtrigger`](https://github.com/Opus10/django-pgtrigger) and [`django-pgviews`](https://github.com/mypebble/django-pgviews).