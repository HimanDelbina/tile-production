# Explicit isolated test configuration.
import os
import tempfile
from pathlib import Path

os.environ['DJANGO_ENV'] = 'test'
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-key-that-is-at-least-50-characters-long-and-secure-enough')
os.environ.setdefault('DJANGO_DEBUG', '0')

from .settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

MEDIA_ROOT = Path(tempfile.gettempdir()) / 'tile_test_media'
STORAGES['staticfiles'] = {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = False
