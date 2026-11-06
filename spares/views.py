"""Главная страница склада и представления отчётов."""

from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import ListView, TemplateView

from spares.context_processors.income_outcome_report import get_income_report, get_outcome_report
from spares.inventory_sheet_models import InventorySheet
from spares.models import Receipt, Stock, WriteOff
from spares.request_models import StockRequest
from spares.report_forms import (
    AnnualReportFilterForm,
    ContractorsReportForm,
    MachineReportForm,
    StockFilterForm,
    TrailersReportForm,
)
from spares.threshold_models import StockMinimum


class WarehouseMainView(LoginRequiredMixin, TemplateView):
    """Показывает сводку склада и последние документы в пределах прав пользователя."""
    template_name = 'warehouse/index.html'

    def get_context_data(self, **kwargs):
        """Собирает доступные остатки, счётчики месяца и недавние операции."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        month_start = today.replace(day=1)
        context['today'] = today
        if user.has_perm('spares.view_stockrequest'):
            pending = StockRequest.objects.filter(status=StockRequest.Status.PENDING)
            if not user.has_perm('spares.approve_stockrequest'):
                pending = pending.filter(created_by=user)
            context['pending_stock_requests'] = pending.count()
        if user.has_perms(('spares.view_inventorysheet', 'spares.approve_inventorysheet')):
            context['pending_inventory_sheets'] = InventorySheet.objects.filter(
                status=InventorySheet.Status.PENDING,
            ).count()
        if user.has_perm('spares.view_stock'):
            context['stock_summary'] = Stock.objects.aggregate(
                positions=Count('pk', filter=Q(actual_balance__gt=0)),
                discrepancies=Count('pk', filter=Q(discrepancy=True)),
            )
        for model, name in ((Receipt, 'receipt'), (WriteOff, 'writeoff')):
            if user.has_perm(f'spares.view_{name}'):
                entries = model.objects.filter(date__lte=today, cancelled_at__isnull=True)
                context[f'{name}_count'] = entries.filter(date__gte=month_start).count()
                context[f'recent_{name}s'] = entries.select_related('spare', 'warehouse', 'measure').order_by(
                    '-date', '-pk',
                )[:5]
        return context


class WarehouseReportMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Проверяет вход и право просмотра отчёта и задаёт ключ выдачи в шаблоне."""
    context_object_name = 'report_data'


class FilteredReportView(WarehouseReportMixin, ListView):
    """Строит отчёт по проведённым документам за выбранный период."""
    @cached_property
    def form(self):
        """Создаёт форму периода и объекта отчёта из параметров GET."""
        return self.form_class(self.request.GET or None)

    def get_queryset(self):
        """Возвращает неотменённые документы по объекту и включительному диапазону дат."""
        if not self.form.is_valid():
            return self.model.objects.none()
        data = self.form.cleaned_data
        return (
            self.model.objects.filter(
                date__range=data['date_range'],
                date__lte=timezone.localdate(),
                cancelled_at__isnull=True,
                **{self.model_field: data[self.form_field]},
            )
            .select_related(*self.related_fields)
            .order_by('-date', '-pk')
        )

    def get_context_data(self, **kwargs):
        """Передаёт фильтры, выбранный объект, период и итоги отобранных документов."""
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        context['report_title'] = self.report_title
        if self.form.is_valid():
            totals = self.object_list.aggregate(total=Sum(self.amount_field), count=Count('pk'))
            context.update(
                report_subject=self.form.cleaned_data[self.form_field],
                report_period=self.form.cleaned_data['date_range'],
                total_amount=totals['total'],
                entry_count=totals['count'],
            )
        return context


class WriteOffReportView(FilteredReportView):
    """Собирает данные списаний для отчёта по технике или прицепам."""
    model = WriteOff
    amount_field = 'total_amount'
    permission_required = 'spares.view_writeoff'
    template_name = 'spares/writeoff_report.html'
    related_fields = ('machine', 'trailer', 'worker', 'spare', 'measure', 'company', 'warehouse')

    def get_context_data(self, **kwargs):
        """Передаёт поле транспорта для общей таблицы списаний."""
        context = super().get_context_data(**kwargs)
        context['vehicle_field'] = self.model_field
        return context


class MachineReportView(WriteOffReportView):
    """Отбирает списания для выбранной единицы техники."""
    form_class = MachineReportForm
    form_field = 'machine'
    model_field = 'machine'
    report_title = 'Отчёт по технике'


class TrailerReportView(WriteOffReportView):
    """Отбирает списания для выбранного прицепа."""
    form_class = TrailersReportForm
    form_field = 'trailers'
    model_field = 'trailer'
    report_title = 'Отчёт по прицепам'


class ContractorReportView(FilteredReportView):
    """Отбирает приход и сумму по выбранному контрагенту."""
    model = Receipt
    form_class = ContractorsReportForm
    form_field = 'contractors'
    model_field = 'contractor'
    amount_field = 'amount'
    permission_required = 'spares.view_receipt'
    template_name = 'spares/contractor_report.html'
    report_title = 'Отчёт по контрагентам'
    related_fields = ('contractor', 'spare', 'measure', 'company', 'warehouse')


class StockReportView(WarehouseReportMixin, ListView):
    """Показывает текущие остатки, расхождения и количество позиций к пополнению."""
    model = Stock
    queryset = Stock.objects.select_related('spare', 'measure', 'company', 'warehouse').order_by('spare__name', 'pk')
    permission_required = 'spares.view_stock'
    template_name = 'spares/stock_report.html'

    @cached_property
    def form(self):
        """Создаёт форму фильтрации складских остатков."""
        return StockFilterForm(self.request.GET or None)

    def get_queryset(self):
        """Отбирает остатки по фильтрам склада и при необходимости только с расхождениями."""
        queryset = self.form.filter_groups(super().get_queryset())
        if self.form.is_valid() and self.form.cleaned_data['discrepancy']:
            queryset = queryset.filter(inventory__isnull=False, discrepancy=True)
        return queryset

    def get_context_data(self, **kwargs):
        """Считает позиции, расхождения, отсутствие остатков и доступные данные пополнения."""
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        context['counts'] = self.object_list.aggregate(
            matches=Count('pk'),
            discrepancies=Count('pk', filter=Q(inventory__isnull=False, discrepancy=True)),
            unavailable=Count('pk', filter=Q(actual_balance__lte=0)),
        )
        if self.request.user.has_perm('spares.view_stockminimum'):
            rules = self.form.filter_groups(StockMinimum.objects.with_available())
            context['replenishment_count'] = rules.below_minimum().count()
        return context


class IncomeOutcomeReportView(WarehouseReportMixin, TemplateView):
    """Показывает годовые сводки прихода и расхода при наличии обоих прав."""
    permission_required = ('spares.view_receipt', 'spares.view_writeoff')
    template_name = 'spares/income_outcome_report.html'

    def get_context_data(self, **kwargs):
        """Проверяет область и передаёт месячные и общие суммы прихода и расхода."""
        context = super().get_context_data(**kwargs)
        form = AnnualReportFilterForm(self.request.GET or None)
        ready = not form.is_bound or form.is_valid()
        context.update(form=form, ready=ready)
        if ready:
            filters = form.cleaned_data if form.is_bound else {}
            income_report = get_income_report(**filters)
            outcome_report = get_outcome_report(**filters)
            context.update(
                income_report=income_report,
                outcome_report=outcome_report,
                income_total=sum((row['year_total'] for row in income_report), Decimal('0.00')),
                outcome_total=sum((row['year_total'] for row in outcome_report), Decimal('0.00')),
                months=('Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'),
            )
        return context
