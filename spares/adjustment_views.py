"""Журнал ручных корректировок, включая записи по инвентаризационным ведомостям."""

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.utils.functional import cached_property
from django.views.generic import ListView

from .forms import StockJournalFilterForm
from .models import StockAdjustment


class AdjustmentFilterForm(StockJournalFilterForm):
    """Дополняет фильтры журнала ссылкой на отдельную корректировку."""
    entry = forms.IntegerField(
        label='Запись', required=False, min_value=1, max_value=2**63 - 1, widget=forms.HiddenInput,
    )


class StockAdjustmentListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Показывает только доступный пользователю журнал с постраничным выводом."""
    model = StockAdjustment
    permission_required = 'spares.view_stockadjustment'
    template_name = 'spares/adjustments/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    @cached_property
    def filters(self):
        """Связывает форму поиска корректировок с параметрами GET."""
        return AdjustmentFilterForm(self.request.GET or None, search_hint='Запчасть, склад, автор или причина')

    def get_queryset(self):
        """Выбирает корректировки по автору, причине, дате или складской позиции."""
        queryset = super().get_queryset().select_related('sheet_line')
        return self.filters.filter_queryset(
            queryset, search_fields=('stock_label', 'actor_name', 'reason'),
            date_field='created_at__date', exact_fields=(('stock', 'stock_id'), ('entry', 'pk')),
        )

    def get_context_data(self, **kwargs):
        """Передаёт фильтры и идентификаторы позиции и записи в шаблон."""
        context = super().get_context_data(**kwargs)
        context['filters'] = self.filters
        data = self.filters.cleaned_data if self.filters.is_valid() else {}
        context['stock_id'] = data.get('stock')
        context['entry_id'] = data.get('entry')
        return context
