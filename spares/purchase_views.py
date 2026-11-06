"""Страницы списка закупок и выгрузки позиций с рассчитанным дефицитом."""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import DecimalField, F
from django.db.models.functions import Round
from django.http import FileResponse, HttpResponseBadRequest
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import ListView

from .purchase_xlsx import make_purchase_workbook
from .report_forms import StockGroupFilterForm
from .threshold_models import StockMinimum


class PurchaseListMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Формирует один набор данных для страницы и файла списка закупок."""
    permission_required = ('spares.view_stock', 'spares.view_stockminimum')

    @cached_property
    def filters(self):
        """Создаёт фильтры склада, фирмы и запчасти из параметров запроса."""
        return StockGroupFilterForm(self.request.GET or None)

    def get_queryset(self):
        """Вычисляет округлённый дефицит и сортирует позиции по складу и названию."""
        shortages = (
            StockMinimum.objects.with_available().below_minimum()
            .annotate(shortage=Round(
                F('minimum') - F('available'), precision=2,
                output_field=DecimalField(max_digits=24, decimal_places=2),
            ))
            .select_related('spare', 'company', 'warehouse', 'measure')
            .order_by('warehouse__name', 'warehouse_id', 'spare__name', 'company__name', 'pk')
        )
        return self.filters.filter_groups(shortages)


class PurchaseListView(PurchaseListMixin, ListView):
    """Показывает закупки постранично с возможностью фильтрации."""
    template_name = 'spares/purchases/list.html'
    context_object_name = 'shortages'
    paginate_by = 30

    def get_context_data(self, **kwargs):
        """Передаёт текущие фильтры в шаблон списка закупок."""
        return super().get_context_data(filters=self.filters, **kwargs)


class PurchaseExportView(PurchaseListMixin, View):
    """Выдаёт полную книгу закупок по выбранным фильтрам."""
    def get(self, request, *args, **kwargs):
        """Проверяет фильтры и отправляет XLSX без ограничения текущей страницей."""
        if self.filters.errors:
            return HttpResponseBadRequest('Исправьте фильтры списка закупок.')
        workbook = make_purchase_workbook(self.get_queryset().iterator())
        return FileResponse(
            workbook, as_attachment=True, filename='warehouse-purchases.xlsx',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
