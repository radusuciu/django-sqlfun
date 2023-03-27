from django import apps

class FunctionConfig(apps.AppConfig):
    name = 'sqlfun'
    verbose_name = 'Django SQL Fun'
    default_auto_field = 'django.db.models.AutoField'

