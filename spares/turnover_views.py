"""Постраничный отчёт и полная выгрузка оборота запчастей."""

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import FileResponse, HttpResponseBadRequest
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import ListView

from .turnover_data import TurnoverReport
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

    @cached_property
    def report(self):
        """Создаёт запрос отчёта только после проверки фильтров."""
        return TurnoverReport(self.filters) if self.filters is not None else None


class TurnoverView(TurnoverMixin, ListView):
    """Показывает выбранный оборот, денежные итоги и постраничную таблицу."""

    template_name = 'spares/turnover.html'
    context_object_name = 'rows'
    paginate_by = 30

    def get_queryset(self):
        """Передаёт пагинатору ключи позиций, которые можно ограничить в SQL."""
        return self.report.positions() if self.report is not None else []

    def paginate_queryset(self, queryset, page_size):
        """Заменяет ключи текущей страницы рассчитанными строками оборота."""
        paginator, page, positions, is_paginated = super().paginate_queryset(queryset, page_size)
        page.object_list = self.report.rows(positions) if self.report is not None else []
        return paginator, page, page.object_list, is_paginated

    def get_context_data(self, **kwargs):
        """Передаёт форме и таблице период и денежные итоги по всем отобранным строкам."""
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        if self.report is not None:
            context['start'], context['end'] = self.filters['date_range']
            context.update(self.report.totals())
        return context


class TurnoverExportView(TurnoverMixin, View):
    """Отдаёт книгу оборота по текущим фильтрам без ограничения страницей."""

    def get(self, request, *args, **kwargs):
        """Проверяет параметры и отправляет готовый XLSX."""
        if self.report is None:
            return HttpResponseBadRequest('Исправьте фильтры отчёта об обороте.')
        return FileResponse(
            turnover_workbook(self.report.export_rows(), self.filters),
            as_attachment=True,
            filename='warehouse-turnover.xlsx',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
