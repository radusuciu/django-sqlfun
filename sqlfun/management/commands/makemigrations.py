import sys

import django
from django.core.management.commands.makemigrations import Command as BaseCommand

from sqlfun.utils import make_sqlfun_migrations


class Command(BaseCommand):
    def handle(self, *args, **options):
        is_check = options.get('check_changes', False)
        # Django only sets its internal self.dry_run when --check is passed,
        # so we must imply dry-run ourselves (Django 4.2+ semantics)
        is_dry_run = options.get('dry_run', False) or is_check
        sqlfun_migration_paths = []

        try:
            sqlfun_migration_paths = make_sqlfun_migrations(
                custom_name=options.get('name'),
                stdout=self.stdout,
                is_dry_run=is_dry_run,
            )
        except django.db.utils.ProgrammingError:
            self.stderr.write(
                '[sqlfun] It seems like the SqlFunDefinition model does not exist yet. '
                'A migration will be generated which must be applied before you can '
                'define custom functions.'
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

        # exits 1 itself if model changes are missing migrations under --check
        result = super().handle(*args, **options)

        if is_check and sqlfun_migration_paths:
            sys.exit(1)

        return result
