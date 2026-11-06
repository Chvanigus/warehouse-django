"""Постраничный отчёт и полная выгрузка оборота запчастей."""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import FileResponse, HttpResponseBadRequest
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import ListView

from .analytics_data import ZERO
from .turnover_data import turnover_rows
from .turnover_forms import TurnoverFilterForm
from .turnover_xlsx import turnover_workbook


class TurnoverMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Ограничивает отчёт пользователями, которым доступны обе стороны оборота."""

    permission_required = ('spares.view_receipt', 'spares.view_writeoff')

    @cached_property
    def form(self):
        """Разбирает параметры GET, сохраняя начальный период для пустого запроса."""
        return TurnoverFilterForm(self.request.GET or None)

    @cached_property
    def filters(self):
        """Возвращает проверенные параметры или признак ошибки."""
        return self.form.filters()

    def get_queryset(self):
        """Строит одинаковый набор строк для страницы и выгрузки."""
        return turnover_rows(self.filters) if self.filters is not None else []


class TurnoverView(TurnoverMixin, ListView):
    """Показывает выбранный оборот, денежные итоги и постраничную таблицу."""

    template_name = 'spares/turnover.html'
    context_object_name = 'rows'
    paginate_by = 30

    def get_context_data(self, **kwargs):
        """Передаёт форме и таблице период и денежные итоги по всем отобранным строкам."""
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        if self.filters is not None:
            context['start'], context['end'] = self.filters['date_range']
            context['receipts_total'] = sum((row['receipts_amount'] for row in self.object_list), ZERO)
            context['writeoffs_total'] = sum((row['writeoffs_amount'] for row in self.object_list), ZERO)
        return context


class TurnoverExportView(TurnoverMixin, View):
    """Отдаёт книгу оборота по текущим фильтрам без ограничения страницей."""

    def get(self, request, *args, **kwargs):
        """Проверяет параметры и отправляет готовый XLSX."""
        if self.filters is None:
            return HttpResponseBadRequest('Исправьте фильтры отчёта об обороте.')
        return FileResponse(
            turnover_workbook(self.get_queryset(), self.filters),
            as_attachment=True,
            filename='warehouse-turnover.xlsx',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
