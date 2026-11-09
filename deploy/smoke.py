"""Проверка HTTP-готовности релиза: база, форма входа и собранные статические файлы."""

import argparse
import json
import sys
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class SmokeError(Exception):
    """Сообщает о доступном HTTP-сервисе, который не прошёл проверку релиза."""


class LoginPage(HTMLParser):
    """Извлекает поля входа и адрес собственных стилей из полученного HTML."""

    def __init__(self):
        """Подготавливает список полей и адрес CSS до разбора страницы."""
        super().__init__()
        self.fields = set()
        self.stylesheet = None

    def handle_starttag(self, tag, attributes):
        """Запоминает имена полей формы и подключение складского CSS."""
        attributes = dict(attributes)
        if tag == 'input':
            self.fields.add(attributes.get('name'))
        if tag == 'link' and 'stylesheet' in (attributes.get('rel') or '').split():
            href = attributes.get('href') or ''
            if urlsplit(href).path == '/static/css/warehouse.css':
                self.stylesheet = href


def fetch(base_url, path, headers, timeout):
    """Загружает ответ с ожидаемым HTTP 200 и ограничением времени запроса."""
    request = Request(urljoin(base_url.rstrip('/') + '/', path), headers=headers)
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise SmokeError(f'{path}: ожидался HTTP 200, получен {response.status}.')
        return response.read(), response.headers.get_content_type()


def verify(base_url, *, host=None, forwarded_https=False, timeout=10):
    """Проверяет реальный веб-сервер, готовность БД, форму входа и раздачу статики."""
    headers = {}
    if host:
        headers['Host'] = host
    if forwarded_https:
        headers['X-Forwarded-Proto'] = 'https'

    health, content_type = fetch(base_url, 'healthz/', headers, timeout)
    if content_type != 'application/json' or json.loads(health) != {'status': 'ok'}:
        raise SmokeError('/healthz/: приложение или база не готовы.')

    html, content_type = fetch(base_url, 'login/', headers, timeout)
    if content_type != 'text/html':
        raise SmokeError('/login/: ожидалась HTML-страница входа.')
    page = LoginPage()
    page.feed(html.decode('utf-8'))
    if not {'username', 'password', 'csrfmiddlewaretoken'} <= page.fields:
        raise SmokeError('/login/: отсутствуют поля входа или CSRF-токен.')
    if not page.stylesheet:
        raise SmokeError('/login/: не подключён /static/css/warehouse.css.')

    stylesheet, content_type = fetch(base_url, page.stylesheet, headers, timeout)
    if content_type != 'text/css' or not stylesheet.strip():
        raise SmokeError('Статические файлы: CSS не выдан или содержит пустой ответ.')

    icons, content_type = fetch(base_url, 'static/images/ui-icons.svg', headers, timeout)
    if content_type != 'image/svg+xml' or not icons.strip():
        raise SmokeError('Статические файлы: SVG-иконки не выданы или содержат пустой ответ.')


def main():
    """Читает параметры HTTP-проверки и возвращает ненулевой код при отказе."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--host', help='Заголовок Host для проверки production через loopback.')
    parser.add_argument('--forwarded-https', action='store_true', help='Передать X-Forwarded-Proto: https.')
    parser.add_argument('--timeout', type=float, default=10, help='Таймаут каждого HTTP-запроса в секундах.')
    arguments = parser.parse_args()
    address = urlsplit(arguments.base_url)
    if address.scheme not in ('http', 'https') or not address.netloc or arguments.timeout <= 0:
        parser.error('Нужен HTTP(S)-адрес сервиса и положительный --timeout.')
    try:
        verify(
            arguments.base_url, host=arguments.host, forwarded_https=arguments.forwarded_https,
            timeout=arguments.timeout,
        )
    except (OSError, URLError, ValueError, SmokeError) as error:
        print(f'Smoke check failed: {error}', file=sys.stderr)
        return 1
    print('Smoke check OK: health, login, static CSS and SVG.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
