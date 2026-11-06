"""Проверка готовности склада и локальный HTTP-запрос для Docker."""

import os
from http.client import HTTPConnection, HTTPException

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def readiness(request):
    """Проверяет доступ к базе и возвращает минимальный статус без деталей окружения."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM django_migrations LIMIT 1')
            ready = cursor.fetchone() is not None
    except DatabaseError:
        ready = False
    return JsonResponse({'status': 'ok' if ready else 'unavailable'}, status=200 if ready else 503)


def check():
    """Проверяет HTTP-ответ через loopback внутри контейнера с боевым заголовком Host."""
    host = os.getenv('ALLOWED_HOSTS', 'localhost').split(',')[0].strip() or 'localhost'
    probe = HTTPConnection('127.0.0.1', 8000, timeout=3)
    try:
        probe.request('GET', '/healthz/', headers={'Host': host, 'X-Forwarded-Proto': 'https'})
        return 0 if probe.getresponse().status == 200 else 1
    except (OSError, HTTPException):
        return 1
    finally:
        probe.close()


if __name__ == '__main__':
    raise SystemExit(check())
