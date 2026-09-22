from django.apps import AppConfig


class ZooConfig(AppConfig):
    # a second app whose label sorts after test_project, for functions that
    # move between apps
    name = 'zoo'
    default_auto_field = 'django.db.models.AutoField'
