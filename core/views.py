"""Представления для стандартных ошибок проекта."""
from django.shortcuts import render


def permission_denied(request, exception):
    """Показывает причину отказа в общем виде и возвращает HTTP-статус 403."""
    return render(request, 'core/403.html', status=403)


def page_not_found(request, exception):
    """Показывает запрошенный путь на странице с HTTP-статусом 404."""
    return render(request, 'core/404.html', {'path': request.path}, status=404)


def server_error(request):
    """Возвращает страницу с HTTP-статусом 500 без деталей исключения."""
    return render(request, 'core/500.html', status=500)
