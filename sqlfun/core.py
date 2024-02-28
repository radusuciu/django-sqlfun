import re
from abc import ABC
from typing import ClassVar, Optional, Type

from django.db.models.expressions import Func
from django.db.models.fields import Field


class SqlFun(Func, ABC):
    _registry: ClassVar[list[Type['SqlFun']]] = []
    sql: str
    output_field: Optional[Field] = None
    app_label: Optional[str] = None

    def __init__(self, *expressions, output_field: Optional[Field] = None, **extra):
        if output_field is None:
            if self.output_field is not None:
                output_field = self.output_field
            else:
                raise ValueError(
                    "The 'output_field' must be defined in the class or provided during instantiation."
                )
        super().__init__(*expressions, output_field=output_field, **extra)

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

    @classmethod
    def deregister(cls):
        """Remove a function from the registry.

        Useful for testing
        """
        cls._registry.remove(cls)

    def as_sql(self, compiler, connection, function=None, **extra_context):
        function_name = self.get_function_name_from_sql()
        return super().as_sql(compiler, connection, function=function_name, **extra_context)
