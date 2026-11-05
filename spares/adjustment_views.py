from re import escape

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.utils.functional import cached_property
from django.views.generic import ListView

from .forms import StockJournalFilterForm
from .models import StockAdjustment


class StockAdjustmentListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = StockAdjustment
    permission_required = 'spares.view_stockadjustment'
    template_name = 'spares/adjustments/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    @cached_property
    def filters(self):
        form = StockJournalFilterForm(self.request.GET or None)
        form.fields['q'].widget.attrs['placeholder'] = 'Запчасть, склад, автор или причина'
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
                Q(stock_label__iregex=pattern) | Q(actor_name__iregex=pattern) | Q(reason__iregex=pattern),
            )
        if data['date_from']:
            queryset = queryset.filter(created_at__date__gte=data['date_from'])
        if data['date_to']:
            queryset = queryset.filter(created_at__date__lte=data['date_to'])
        if data['stock']:
            queryset = queryset.filter(stock_id=data['stock'])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filters'] = self.filters
        context['stock_id'] = self.filters.cleaned_data.get('stock') if self.filters.is_valid() else None
        return context
