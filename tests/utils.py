
from django.db import connection


def function_exists(function_name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM information_schema.routines WHERE routine_name = %s', [function_name])
        return cursor.fetchone()[0] == 1
