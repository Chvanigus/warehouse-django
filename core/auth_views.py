"""Управление паролем собственной учётной записи."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache


@method_decorator(never_cache, name='dispatch')
class AccountPasswordChangeView(PasswordChangeView):
    """Меняет пароль после проверки текущего пароля и сохраняет сеанс."""

    template_name = 'warehouse/password_change.html'
    success_url = reverse_lazy('spares:warehouse_main')

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Проверяет текущий пароль и активность по заблокированной записи пользователя."""
        account = get_user_model().objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
        if account is None:
            raise PermissionDenied
        request.user = account
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Подтверждает смену пароля после его сохранения и обновления сеанса."""
        response = super().form_valid(form)
        messages.success(self.request, 'Пароль изменён.')
        return response
