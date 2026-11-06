"""Настройки склада для локального запуска и развёртывания в Docker."""

import os
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_list(name, default=''):
    """Читает значения переменной через запятую и убирает пробелы и пустые элементы."""
    values = map(str.strip, os.getenv(name, default).split(','))
    return [value for value in values if value]


def env_flag(name):
    """Читает флаг окружения и останавливает запуск при опечатке в значении."""
    value = os.getenv(name, '0')
    if value not in ('0', '1'):
        raise ImproperlyConfigured(f'{name} должен иметь значение 0 или 1.')
    return value == '1'


def validate_production_settings():
    """Проверяет обязательные настройки публичного экземпляра до запуска приложения."""
    if DEBUG or not HTTPS:
        raise ImproperlyConfigured('Для боевого режима нужны DEBUG=0 и WAREHOUSE_HTTPS=1.')
    if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
        raise ImproperlyConfigured('Укажите длинный случайный SECRET_KEY для боевого режима.')
    hostname = r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if len(ALLOWED_HOSTS) != 1 or not re.fullmatch(hostname, ALLOWED_HOSTS[0], re.IGNORECASE | re.ASCII):
        raise ImproperlyConfigured('Укажите один публичный домен без схемы, порта и подстановочных знаков.')
    if CSRF_TRUSTED_ORIGINS != [f'https://{ALLOWED_HOSTS[0]}']:
        raise ImproperlyConfigured('CSRF_TRUSTED_ORIGINS должен содержать HTTPS-адрес публичного домена.')


DEBUG = env_flag('DEBUG')
HTTPS = env_flag('WAREHOUSE_HTTPS')
PRODUCTION = env_flag('WAREHOUSE_PRODUCTION')
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Set SECRET_KEY before running Warehouse with DEBUG disabled.')
    SECRET_KEY = 'django-insecure-warehouse-local-development'

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')
if PRODUCTION:
    validate_production_settings()
LOGIN_URL = 'spares:login'
LOGIN_REDIRECT_URL = 'spares:warehouse_main'

# Включайте за прокси, который завершает TLS и сам устанавливает X-Forwarded-Proto.
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core.apps.CoreConfig',
    'spares.apps.SparesConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'warehouse.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'warehouse.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.getenv('DATABASE_PATH') or BASE_DIR / 'db.sqlite3',
        # Блокировка записи нужна до чтения остатка при складской операции.
        'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
