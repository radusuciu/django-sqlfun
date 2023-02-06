import logging

from django_sqlfun import SqlFun

from django import apps
from django.db.models import signals

logger = logging.getLogger('django_sqlfun')


class FunctionConfig(apps.AppConfig):
    """Create or update all functions in the database, before all other migrations have been run."""

    has_run = False
    name = 'django_sqlfun'
    verbose_name = 'Django SQL Functions'

    def ready(self):
        signals.pre_migrate.connect(self.update)

    def update(self, **kwargs):
        """Create or update all functions in the database."""
        if self.has_run:
            return

        logger.info('[django_sqlfun] Updating custom functions in the database.')

        for function in SqlFun._registry:
            function_name = function.get_function_name_from_sql()
            logger.info(f'[django_sqlfun] Updating function {function_name}.')
            function.update()

        self.has_run = True
