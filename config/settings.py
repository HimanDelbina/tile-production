import os
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# Explicit Environment Selection: 'production', 'development', or 'test'
DJANGO_ENV = os.getenv('DJANGO_ENV', 'production').lower()
BUILDING_STATIC = os.getenv('BUILDING_STATIC', '0') == '1'

# Secret Key validation
if DJANGO_ENV == 'production' and not BUILDING_STATIC:
    SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
    if not SECRET_KEY:
        raise ImproperlyConfigured("متغیر محیطی ضروری DJANGO_SECRET_KEY در محیط Production تنظیم نشده است.")
    if len(SECRET_KEY) < 50 or SECRET_KEY.startswith('django-insecure-') or 'REPLACE_WITH' in SECRET_KEY:
        raise ImproperlyConfigured(
            "مقدار DJANGO_SECRET_KEY برای استقرار عملیاتی نامعتبر یا ضعیف است. کلید تصادفی با حداقل ۵۰ کاراکتر تنظیم کنید."
        )
else:
    SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'build-or-dev-only-secret-key-not-for-production-use-0000000000000000')

# Debug Mode
if DJANGO_ENV == 'production':
    DEBUG = False
else:
    DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'

# Hosts Configuration
raw_hosts = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
ALLOWED_HOSTS = list(dict.fromkeys([h.strip() for h in raw_hosts if h.strip()] + ['127.0.0.1', 'localhost']))

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'production',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'production.context_processors.shell',
            ]
        },
    }
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database Configuration
if DJANGO_ENV == 'production':
    if BUILDING_STATIC:
        # Dummy database during image build when running collectstatic without database service
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        }
    else:
        missing_db_vars = [
            var for var in ['POSTGRES_HOST', 'POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD']
            if not os.environ.get(var)
        ]
        if missing_db_vars:
            raise ImproperlyConfigured(
                f"در محیط Production استفاده از PostgreSQL الزامی است و هیچ fallback به SQLite وجود ندارد. متغیرهای ضروری زیر تنظیم نشده‌اند: {', '.join(missing_db_vars)}"
            )
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.environ['POSTGRES_DB'],
                'USER': os.environ['POSTGRES_USER'],
                'PASSWORD': os.environ['POSTGRES_PASSWORD'],
                'HOST': os.environ['POSTGRES_HOST'],
                'PORT': os.getenv('POSTGRES_PORT', '5432'),
                'CONN_MAX_AGE': 60,
                'CONN_HEALTH_CHECKS': True,
            }
        }
elif DJANGO_ENV == 'test':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
else:
    # Development mode: prefer PostgreSQL if POSTGRES_HOST is specified, otherwise fallback to SQLite
    if os.getenv('POSTGRES_HOST'):
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.getenv('POSTGRES_DB', 'tileproduction'),
                'USER': os.getenv('POSTGRES_USER', 'tileapp'),
                'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
                'HOST': os.getenv('POSTGRES_HOST', 'db'),
                'PORT': os.getenv('POSTGRES_PORT', '5432'),
                'CONN_MAX_AGE': 60,
                'CONN_HEALTH_CHECKS': True,
            }
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

# Static Files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media Storage
MEDIA_ROOT = Path(os.getenv('DJANGO_MEDIA_ROOT', str(BASE_DIR / 'media')))
MEDIA_URL = '/media/'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Security & Cookies
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.getenv('DJANGO_COOKIE_SECURE', '1' if DJANGO_ENV == 'production' else '0') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

# Reverse Proxy & SSL Redirect
if os.getenv('DJANGO_TRUST_PROXY', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_SSL_REDIRECT = os.getenv('DJANGO_SSL_REDIRECT', '0') == '1'
SECURE_REDIRECT_EXEMPT = [r'^health/?$']

# HSTS Configuration
SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('DJANGO_HSTS_INCLUDE_SUBDOMAINS', '0') == '1'
SECURE_HSTS_PRELOAD = os.getenv('DJANGO_HSTS_PRELOAD', '0') == '1'

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Limits
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('DJANGO_MAX_UPLOAD_SIZE', 10 * 1024 * 1024))
DJANGO_MAX_UPLOAD_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
DJANGO_MAX_IMPORT_ROWS = int(os.getenv('DJANGO_MAX_IMPORT_ROWS', 2000))

CSRF_FAILURE_VIEW = 'production.views.csrf_failure'
