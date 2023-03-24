import re
from abc import ABC, abstractmethod


    sql: str

    def __init_subclass__(cls, **kwargs):
        if not hasattr(cls, 'sql') or not isinstance(cls.sql, str):
            raise NotImplementedError("Subclass must define the 'sql' class variable as a string.")
        cls._registry.append(cls)

    @classmethod
    def get_function_name_from_sql(cls) -> str:
        """Get the function name from the SQL definition"""

        pattern = re.compile(r'FUNCTION.+?(\w+).+')

        if match := pattern.search(cls.sql):
            return match.group(1)
        else:
            raise ValueError('Could not determine function name from SQL definition.')

    @classmethod
    def update(cls):
        """Create or update the function in the database"""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(cls.sql)
