import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-test-key'

DEBUG = True

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'sqlfun',
    'test_project',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'test_sqlfun',
        'USER': 'test',
        'PASSWORD': 'test',
        'HOST': 'localhost',
        'PORT': int(os.environ.get('SQLFUN_TEST_DB_PORT', '5432')),
    }
}

# second alias pointing at the same server, for --database threading tests
DATABASES['secondary'] = {
    **DATABASES['default'],
    'TEST': {'MIRROR': 'default'},
}

TIME_ZONE = 'UTC'
USE_TZ = True
