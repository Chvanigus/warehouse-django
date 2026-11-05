from re import escape

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import DeleteView, DetailView, FormView, ListView

from .forms import JournalFilterForm
from .models import Stock
from .operation_views import OperationCancellationForm
from .transfer_forms import TransferForm
from .transfer_models import StockTransfer, cancel_transfer, post_transfer


class TransferReadMixin(LoginRequiredMixin, PermissionRequiredMixin):
    permission_required = 'spares.view_stocktransfer'
    queryset = StockTransfer.objects.select_related('spare', 'company', 'measure', 'from_warehouse', 'to_warehouse')


class TransferListView(TransferReadMixin, ListView):
    template_name = 'spares/transfers/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    @cached_property
    def filters(self):
        form = JournalFilterForm(self.request.GET or None)
        form.fields['q'].widget.attrs['placeholder'] = 'Запчасть, склад или автор'
        return form

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.filters.is_bound:
            return queryset
        if not self.filters.is_valid():
            return queryset.none()

        data = self.filters.cleaned_data
        if data['q']:
            pattern = escape(data['q'])
            queryset = queryset.filter(
                Q(spare__name__iregex=pattern) | Q(from_warehouse__name__iregex=pattern)
                | Q(to_warehouse__name__iregex=pattern) | Q(actor_name__iregex=pattern),
            )
        if data['date_from']:
            queryset = queryset.filter(date__gte=data['date_from'])
        if data['date_to']:
            queryset = queryset.filter(date__lte=data['date_to'])
        return queryset

    def get_context_data(self, **kwargs):
        return super().get_context_data(filters=self.filters, **kwargs)


class TransferDetailView(TransferReadMixin, DetailView):
    template_name = 'spares/transfers/detail.html'
    context_object_name = 'transfer'


class TransferCancelView(TransferReadMixin, DeleteView):
    permission_required = ('spares.view_stocktransfer', 'spares.delete_stocktransfer')
    template_name = 'spares/transfers/cancel.html'
    context_object_name = 'transfer'
    form_class = OperationCancellationForm
    http_method_names = ['get', 'head', 'post', 'options']

    def get_queryset(self):
        return super().get_queryset().filter(cancelled_at__isnull=True)

    def form_valid(self, form):
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
    permission_required = 'spares.add_stocktransfer'
    template_name = 'spares/transfers/form.html'
    form_class = TransferForm

    def get_initial(self):
        initial = super().get_initial()
        stock_id = self.request.GET.get('stock', '')
        if stock_id.isdecimal() and len(stock_id) <= 18:
            initial['source'] = Stock.objects.filter(
                pk=int(stock_id), actual_balance__gt=0,
            ).values_list('pk', flat=True).first()
        return initial

    def form_valid(self, form):
        try:
            self.transfer = post_transfer(actor=self.request.user, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, f'Перемещение № {self.transfer.pk} проведено.')
        return super().form_valid(form)

    def get_success_url(self):
        if self.request.user.has_perm('spares.view_stocktransfer'):
            return reverse('transfers:detail', args=[self.transfer.pk])
        return reverse('spares:warehouse_main')
