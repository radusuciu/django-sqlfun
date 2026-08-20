import sys

from django.core.management.base import CommandError
from django.core.management.commands.makemigrations import Command as BaseCommand

from sqlfun.naming import SqlFunError
from sqlfun.utils import make_sqlfun_migrations


class Command(BaseCommand):
    def handle(self, *args, **options):
        is_check = options.get('check_changes', False)
        # Django only sets its internal self.dry_run when --check is passed,
        # so we must imply dry-run ourselves (Django 4.2+ semantics)
        is_dry_run = options.get('dry_run', False) or is_check

        # Django's own makemigrations runs first: a function signature that
        # references a type created by a still-pending model migration must
        # not block generation of that very migration, and freshly written
        # model migrations become dependencies of the sqlfun migration
        base_exit = None
        try:
            result = super().handle(*args, **options)
        except SystemExit as exit_error:
            # under --check the base command exits nonzero on pending model
            # changes without returning; run the sqlfun check before re-exiting
            base_exit = exit_error
            result = None

        sqlfun_migration_paths = []

        try:
            sqlfun_migration_paths = make_sqlfun_migrations(
                custom_name=options.get('name'),
                app_labels=args or None,
                stdout=self.stdout,
                is_dry_run=is_dry_run,
            )
        except SqlFunError as error:
            raise CommandError(
                f'[sqlfun] Could not resolve a function signature: {error}\n'
                '[sqlfun] No sqlfun migration was generated. If the signature '
                'references a type or table created by a pending migration, run '
                '`migrate` and re-run makemigrations; otherwise fix the SQL '
                'definition above.'
            ) from error
        except Exception as e:
            if is_check:
                raise CommandError(
                    '[sqlfun] Could not evaluate sqlfun functions for --check: '
                    f'{e}'
                ) from e
            self.stderr.write(
                '[sqlfun] Could not make migrations for sqlfun functions.'
            )
            if options.get('verbosity', 0) > 0:
                self.stderr.write(f'Exception details: {e}')
                import traceback
                traceback.print_exc(file=self.stderr)

        if is_check and sqlfun_migration_paths:
            self.stderr.write(
                '[sqlfun] sqlfun function changes are missing migrations.'
            )
            sys.exit(1)

        if base_exit is not None:
            raise base_exit

        return result
