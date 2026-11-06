"""Представление аналитики с раздельной проверкой прав на каждый раздел."""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.utils.functional import cached_property
from django.views.generic import TemplateView

from spares.analytics_data import build_analytics, shift_month
from spares.analytics_forms import AnalyticsFilterForm


def period_presets(today):
    """Возвращает короткие диапазоны, заканчивающиеся в текущем месяце."""
    end = today.isoformat()[:7]
    return [
        {'label': label, 'start': shift_month(today, 1 - months).isoformat()[:7], 'end': end}
        for months, label in ((1, 'Этот месяц'), (3, '3 месяца'), (6, '6 месяцев'), (12, '12 месяцев'))
    ]


class AnalyticsView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Показывает только те показатели, для которых выданы права просмотра."""

    template_name = 'spares/analytics.html'

    @cached_property
    def visibility(self):
        """Определяет доступность рядов операций, остатков и данных пополнения."""
        user = self.request.user
        show_stock = user.has_perm('spares.view_stock')
        return {
            'show_receipts': user.has_perm('spares.view_receipt'),
            'show_writeoffs': user.has_perm('spares.view_writeoff'),
            'show_stock': show_stock,
            'show_minimums': show_stock and user.has_perm('spares.view_stockminimum'),
        }

    def has_permission(self):
        """Разрешает вход, если доступен хотя бы один раздел аналитики."""
        return any(self.visibility.values())

    def get_context_data(self, **kwargs):
        """Вычисляет аналитику после проверки фильтров и передаёт выбранную область в шаблон."""
        context = super().get_context_data(**kwargs)
        data = self.request.GET
        if not (self.visibility['show_receipts'] or self.visibility['show_writeoffs']):
            data = data.copy()
            data.pop('start', None)
            data.pop('end', None)
        form = AnalyticsFilterForm(data or None)
        filters = form.filters()
        context.update(self.visibility, form=form, ready=filters is not None)
        if self.visibility['show_receipts'] or self.visibility['show_writeoffs']:
            context['period_presets'] = period_presets(form.today)
        if filters is not None:
            start, end = filters['date_range']
            company, warehouse = filters['company'], filters['warehouse']
            context.update(build_analytics(start, end, company=company, warehouse=warehouse, **self.visibility))
            context.update(company=company, warehouse=warehouse, snapshot_date=form.today)
        return context
