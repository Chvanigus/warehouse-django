"""Контроль русскоязычной документации в собственном Python-коде проекта."""

import ast
import re
import tokenize
from unittest import TestCase

from django.conf import settings


CYRILLIC = re.compile(r'[А-Яа-яЁё]')
DOCUMENTABLE_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def project_sources():
    """Перечисляет Python-файлы проекта, включая миграции и тесты."""
    root = settings.BASE_DIR
    yield root / 'manage.py'
    for package in ('core', 'spares', 'warehouse'):
        yield from sorted((root / package).rglob('*.py'))


class DocstringTests(TestCase):
    """Проверяет наличие описаний без импорта анализируемых файлов."""

    def test_python_definitions_have_russian_docstrings(self):
        """Собирает полный список определений без русскоязычного описания."""
        missing = []
        for path in project_sources():
            with tokenize.open(path) as source:
                tree = ast.parse(source.read(), filename=str(path))
            relative = path.relative_to(settings.BASE_DIR).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, DOCUMENTABLE_NODES) and not CYRILLIC.search(ast.get_docstring(node) or ''):
                    missing.append(f'{relative}:{getattr(node, "lineno", 1)} — {getattr(node, "name", "модуль")}')

        self.assertFalse(missing, 'Добавьте русскоязычные docstring в следующих местах:\n' + '\n'.join(missing))
