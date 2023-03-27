
from django.core.management.commands.makemigrations import Command as BaseCommand

from sqlfun.utils import make_sqlfun_migrations


class Command(BaseCommand):
    def handle(self, *args, **options):

        try:
            make_sqlfun_migrations(
                custom_name=options.get('name'),
                stdout=self.stdout,
                is_dry_run=options.get('dry_run')
            )
        except Exception as e:
            self.stderr.write(
                '[sqlfun] Could not make migrations for sqlfun functions. '
                'Is the SqlFunDefinition model created properly?'
            )
            if options.get('verbosity', 0) > 0:
                self.stderr.write(f'Exception details: {e}')
                import traceback
                traceback.print_exc(file=self.stderr)

        super().handle(*args, **options)
