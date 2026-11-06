"""Подготавливает приложение Django для запуска через WSGI, в том числе Gunicorn."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'warehouse.settings')

application = get_wsgi_application()
