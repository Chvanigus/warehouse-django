"""Управление обычными складскими учётными записями через интерфейс приложения."""

from re import escape

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import Count, Min, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.views.generic import CreateView, FormView, ListView, UpdateView

from .warehouse_admin_forms import (
    ROLE_BY_GROUP,
    WarehouseUserCreateForm,
    WarehouseUserFilterForm,
    WarehouseUserPasswordForm,
    WarehouseUserUpdateForm,
    safe_warehouse_groups,
)
from .warehouse_roles import WAREHOUSE_ROLE_LABELS, WAREHOUSE_ROLES


def managed_warehouse_users():
    """Возвращает обычных сотрудников с одной складской группой и без прямых прав."""
    group_ids = [group.pk for group in safe_warehouse_groups().values()]
    return (
        get_user_model().objects.filter(is_staff=False, is_superuser=False, user_permissions__isnull=True)
        .annotate(group_count=Count('groups'), warehouse_group=Min('groups__name'))
        .filter(group_count=1, groups__in=group_ids)
        .order_by('username', 'pk')
    )


class WarehouseUserManagementMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Ограничивает раздел администраторами складских учётных записей."""

    permission_required = 'spares.manage_warehouse_users'
    success_url = reverse_lazy('warehouse_admin:users')


class WarehouseUserMutationMixin(WarehouseUserManagementMixin):
    """Проверяет текущие полномочия в той же транзакции, что и изменение."""

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Не использует кэш прав, если сотрудника отключили или сменили его роль."""
        actor = get_user_model().objects.filter(pk=request.user.pk, is_active=True).first()
        if actor is None or not actor.has_perms(self.get_permission_required()):
            return self.handle_no_permission()
        request.user = actor
        return super().post(request, *args, **kwargs)


class WarehouseUserListView(WarehouseUserManagementMixin, ListView):
    """Показывает доступные для управления учётные записи сотрудников."""

    template_name = 'spares/warehouse_admin/users.html'
    paginate_by = 30

    @cached_property
    def filters(self):
        """Проверяет параметры поиска и фильтрации списка."""
        return WarehouseUserFilterForm(self.request.GET or None)

    def get_queryset(self):
        """Ограничивает список по логину или имени, роли и активности."""
        accounts = managed_warehouse_users()
        if not self.filters.is_bound:
            return accounts
        if not self.filters.is_valid():
            return accounts.none()
        values = self.filters.cleaned_data
        if values['q']:
            pattern = escape(values['q'])
            accounts = accounts.filter(Q(username__iregex=pattern) | Q(first_name__iregex=pattern))
        if values['role']:
            accounts = accounts.filter(warehouse_group=WAREHOUSE_ROLES[values['role']])
        if values['status']:
            accounts = accounts.filter(is_active=values['status'] == 'active')
        return accounts

    def get_context_data(self, **kwargs):
        """Передаёт в шаблон фильтры и русские названия ролей сотрудников."""
        context = super().get_context_data(**kwargs)
        rows = [
            (account, WAREHOUSE_ROLE_LABELS[ROLE_BY_GROUP[account.warehouse_group]])
            for account in context['object_list']
        ]
        context.update(filters=self.filters, rows=rows)
        return context


class WarehouseUserWriteMixin(WarehouseUserMutationMixin):
    """Сохраняет учётную запись и назначает ровно одну выбранную складскую роль."""

    template_name = 'spares/warehouse_admin/account_form.html'

    def form_valid(self, form):
        """Сохраняет поля учётной записи и заменяет членство в складской группе."""
        response = super().form_valid(form)
        self.object.groups.set([form.cleaned_data['role']])
        messages.success(self.request, self.success_message)
        return response


class WarehouseUserCreateView(WarehouseUserWriteMixin, CreateView):
    """Регистрирует сотрудника с паролем и выбранной ролью."""

    form_class = WarehouseUserCreateForm
    extra_context = {'title': 'Добавить сотрудника'}
    success_message = 'Сотрудник добавлен.'


class WarehouseUserUpdateView(WarehouseUserWriteMixin, UpdateView):
    """Изменяет имя, роль и состояние доступной учётной записи."""

    form_class = WarehouseUserUpdateForm
    context_object_name = 'account'
    extra_context = {'title': 'Изменить сотрудника'}
    success_message = 'Изменения сохранены.'

    def get_queryset(self):
        """Исключает привилегированные и внешние учётные записи из редактирования."""
        return managed_warehouse_users()

    def get_form_kwargs(self):
        """Передаёт администратора в форму для защиты его собственной учётной записи."""
        return {
            **super().get_form_kwargs(), 'actor': self.request.user,
            'role_key': ROLE_BY_GROUP[self.object.warehouse_group],
        }


class WarehouseUserPasswordView(WarehouseUserMutationMixin, FormView):
    """Назначает новый пароль только сотруднику из управляемого списка."""

    template_name = 'spares/warehouse_admin/account_form.html'
    form_class = WarehouseUserPasswordForm
    extra_context = {'title': 'Задать новый пароль'}

    @cached_property
    def account(self):
        """Проверяет, что сотрудник доступен администратору для управления."""
        return get_object_or_404(managed_warehouse_users(), pk=self.kwargs['pk'])

    def get_form_kwargs(self):
        """Передаёт выбранного сотрудника для проверки сложности нового пароля."""
        return {**super().get_form_kwargs(), 'user': self.account}

    def get_context_data(self, **kwargs):
        """Показывает логин сотрудника, для которого меняется пароль."""
        return super().get_context_data(account=self.account, **kwargs)

    def form_valid(self, form):
        """Сохраняет новый пароль и обновляет собственный сеанс при необходимости."""
        account = form.save()
        if account.pk == self.request.user.pk:
            update_session_auth_hash(self.request, account)
        messages.success(self.request, 'Новый пароль сохранён.')
        return super().form_valid(form)
