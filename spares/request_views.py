"""Очередь, карточка и решения по складским заявкам."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import NoReverseMatch, reverse
from django.views import View
from django.views.generic import DetailView, ListView

from .request_details import describe_request
from .request_models import StockRequest
from .request_services import approve_stock_request, reject_stock_request


RESULT_VIEW_PERMISSIONS = {
    'operations:receipts': 'spares.view_receipt',
    'operations:writeoffs': 'spares.view_writeoff',
    'invoices:detail': 'spares.view_receipt',
    'transfers:detail': 'spares.view_stocktransfer',
}


class StockRequestAccessMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Ограничивает видимость заявок правом просмотра и собственным авторством."""

    permission_required = 'spares.view_stockrequest'

    def get_queryset(self):
        """Даёт согласующему полную очередь, а другим пользователям — свои заявки."""
        queryset = StockRequest.objects.all()
        if self.request.user.has_perm('spares.approve_stockrequest'):
            return queryset
        return queryset.filter(created_by_id=self.request.user.pk)


class StockRequestListView(StockRequestAccessMixin, ListView):
    """Показывает постраничную очередь заявок с фильтром состояния."""

    template_name = 'spares/stock_requests/list.html'
    context_object_name = 'stock_requests'
    paginate_by = 30

    def get_status(self):
        """Выбирает допустимый статус, отдавая приоритет ожидающим решения заявкам."""
        default = StockRequest.Status.PENDING if self.request.user.has_perm('spares.approve_stockrequest') else 'all'
        status = self.request.GET.get('status', default)
        return status if status in ('all', *StockRequest.Status.values) else default

    def get_queryset(self):
        """Фильтрует видимую пользователю очередь по текущей вкладке."""
        queryset = super().get_queryset()
        status = self.get_status()
        return queryset if status == 'all' else queryset.filter(status=status)

    def get_context_data(self, **kwargs):
        """Передаёт текущую вкладку и её соседние состояния в шаблон."""
        return super().get_context_data(
            status=self.get_status(), statuses=(('all', 'Все'), *StockRequest.Status.choices), **kwargs,
        )


def _result_url(stock_request, user):
    """Строит локальную ссылку на документ, доступный пользователю по его правам."""
    result = stock_request.result
    if not result:
        return ''
    try:
        route = result['route']
        permission = RESULT_VIEW_PERMISSIONS.get(route)
        if permission is None or not user.has_perm(permission):
            return ''
        if 'query' in result:
            return reverse(route, query=result['query'])
        return reverse(route, args=[result['pk']])
    except (NoReverseMatch, KeyError, TypeError, ValueError):
        return ''


class StockRequestDetailView(StockRequestAccessMixin, DetailView):
    """Показывает сохранённый ввод, статус и доступные действия по заявке."""

    template_name = 'spares/stock_requests/detail.html'
    context_object_name = 'stock_request'

    def get_context_data(self, **kwargs):
        """Добавляет реквизиты, результат проведения и проверку отличия автора от согласующего."""
        fields, lines = describe_request(self.object)
        user = self.request.user
        return super().get_context_data(
            fields=fields, lines=lines, result_url=_result_url(self.object, user),
            can_review=(
                self.object.status == StockRequest.Status.PENDING
                and self.object.created_by_id != user.pk
                and user.has_perm('spares.approve_stockrequest')
            ),
            **kwargs,
        )


class StockRequestReviewView(StockRequestAccessMixin, View):
    """Принимает решение по заявке только через POST уполномоченного сотрудника."""

    permission_required = ('spares.view_stockrequest', 'spares.approve_stockrequest')
    approve = False

    def post(self, request, pk):
        """Передаёт решение в транзакционный сервис и сообщает результат в карточке."""
        stock_request = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            if self.approve:
                approve_stock_request(stock_request.pk, actor=request.user)
                messages.success(request, 'Заявка согласована, документ проведён.')
            else:
                reject_stock_request(stock_request.pk, actor=request.user, reason=request.POST.get('reason', ''))
                messages.success(request, 'Заявка отклонена.')
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        return redirect('stock_requests:detail', pk=stock_request.pk)
