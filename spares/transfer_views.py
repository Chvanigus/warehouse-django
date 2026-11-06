"""Страницы перемещений между складами и обработка их отмены."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import DeleteView, DetailView, FormView, ListView

from .forms import JournalFilterForm
from .models import Stock
from .operation_views import OperationCancellationForm, redirect_to_pending_request
from .request_models import StockRequest
from .request_operations import serialize_form_data
from .request_services import submit_stock_request
from .transfer_forms import TransferForm
from .transfer_models import StockTransfer, cancel_transfer


class TransferReadMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Определяет право просмотра и набор связей для страниц перемещений."""
    permission_required = 'spares.view_stocktransfer'
    queryset = StockTransfer.objects.select_related('spare', 'company', 'measure', 'from_warehouse', 'to_warehouse')


class TransferListView(TransferReadMixin, ListView):
    """Показывает журнал перемещений с поиском и фильтрацией по датам."""
    template_name = 'spares/transfers/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    @cached_property
    def filters(self):
        """Подготавливает форму поиска по запчасти, складу и автору."""
        return JournalFilterForm(self.request.GET or None, search_hint='Запчасть, склад или автор')

    def get_queryset(self):
        """Применяет поиск и включительные границы дат к перемещениям."""
        return self.filters.filter_queryset(
            super().get_queryset(), search_fields=('spare__name', 'from_warehouse__name', 'to_warehouse__name', 'actor_name'),
        )

    def get_context_data(self, **kwargs):
        """Передаёт активные фильтры в шаблон журнала."""
        return super().get_context_data(filters=self.filters, **kwargs)


class TransferDetailView(TransferReadMixin, DetailView):
    """Показывает реквизиты, количество и состояние одного перемещения."""
    template_name = 'spares/transfers/detail.html'
    context_object_name = 'transfer'


class TransferCancelView(TransferReadMixin, DeleteView):
    """Отменяет проведённое перемещение с обязательной причиной."""
    permission_required = ('spares.view_stocktransfer', 'spares.delete_stocktransfer')
    template_name = 'spares/transfers/cancel.html'
    context_object_name = 'transfer'
    form_class = OperationCancellationForm
    http_method_names = ['get', 'head', 'post', 'options']

    def get_queryset(self):
        """Оставляет только перемещения, которые ещё можно отменить."""
        return super().get_queryset().filter(cancelled_at__isnull=True)

    def form_valid(self, form):
        """Передаёт отмену в сервис и показывает актуальный документ."""
        try:
            self.object = cancel_transfer(
                self.object, actor=self.request.user, reason=form.cleaned_data['reason'],
            )
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Перемещение отменено. Документ сохранён в журнале.')
        return HttpResponseRedirect(reverse('transfers:detail', args=[self.object.pk]))


class TransferCreateView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    """Принимает заявку на перемещение или сразу проводит его по правам автора."""
    permission_required = ('spares.add_stocktransfer', 'spares.add_stockrequest')
    template_name = 'spares/transfers/form.html'
    form_class = TransferForm

    def get_initial(self):
        """Подставляет исходную позицию с положительным остатком при переходе по ссылке."""
        initial = super().get_initial()
        stock_id = self.request.GET.get('stock', '')
        if stock_id.isdecimal() and len(stock_id) <= 18:
            initial['source'] = Stock.objects.filter(
                pk=int(stock_id), actual_balance__gt=0,
            ).values_list('pk', flat=True).first()
        return initial

    def form_valid(self, form):
        """Сохраняет заявку и открывает её или проведённое перемещение."""
        try:
            stock_request = submit_stock_request(
                StockRequest.Kind.TRANSFER, serialize_form_data(form.cleaned_data),
                actor=self.request.user, title=f'Перемещение · {form.cleaned_data["source"].spare}',
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        if stock_request.status == StockRequest.Status.PENDING:
            destination = (
                'transfers:list' if self.request.user.has_perm('spares.view_stocktransfer') else 'spares:warehouse_main'
            )
            return redirect_to_pending_request(self.request, stock_request, reverse(destination))
        transfer_id = stock_request.result['pk']
        messages.success(self.request, f'Перемещение № {transfer_id} проведено.')
        if self.request.user.has_perm('spares.view_stocktransfer'):
            return redirect('transfers:detail', pk=transfer_id)
        return redirect('spares:warehouse_main')
