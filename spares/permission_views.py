"""Повторная проверка складских полномочий перед изменением данных."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .validators import load_operation_actor


def require_current_permissions(view):
    """Внутри транзакции обновляет пользователя запроса и проверяет права представления."""
    try:
        view.request.user = load_operation_actor(view.request.user, 'Сеанс пользователя завершён.')
    except ValidationError as error:
        raise PermissionDenied from error
    if not view.has_permission():
        raise PermissionDenied


class CurrentPermissionPostMixin:
    """Объединяет повторную проверку прав, обработку формы и запись в одной транзакции."""

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Проверяет актуальные права после входа в транзакцию, затем обрабатывает запрос."""
        require_current_permissions(self)
        return super().post(request, *args, **kwargs)
