import django
from django.core.management.base import CommandError
from django.core.management.commands.makemigrations import Command as BaseCommand

from sqlfun.naming import SqlFunError
from sqlfun.utils import make_sqlfun_migrations


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            make_sqlfun_migrations(
                custom_name=options.get('name'),
                stdout=self.stdout,
                is_dry_run=options.get('dry_run'),
            )
        except SqlFunError as error:
            raise CommandError(
                f'[sqlfun] Could not resolve a function signature: {error}\n'
                '[sqlfun] No sqlfun migration was generated. Fix the SQL definition '
                'above and re-run makemigrations.'
            ) from error
        except django.db.utils.ProgrammingError:
            self.stderr.write(
                '[sqlfun] It seems like the SqlFunDefinition model does not exist yet. '
                'A migration will be generated which must be applied before you can '
                'define custom functions.'
            )

        return super().handle(*args, **options)
