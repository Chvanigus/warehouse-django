"""Views for the warehouse dashboard and reports."""
import re

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import ListView, TemplateView

from spares.context_processors.income_outcome_report import get_income_report, get_outcome_report
from spares.models import Receipt, Stock, WriteOff
from spares.report_forms import ContractorsReportForm, MachineReportForm, StockFilterForm, TrailersReportForm


class WarehouseMainView(LoginRequiredMixin, TemplateView):
    template_name = 'warehouse/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        month_start = today.replace(day=1)
        context['today'] = today
        if user.has_perm('spares.view_stock'):
            context['stock_summary'] = Stock.objects.aggregate(
                positions=Count('pk', filter=Q(actual_balance__gt=0)),
                discrepancies=Count('pk', filter=Q(discrepancy=True)),
            )
        for model, name in ((Receipt, 'receipt'), (WriteOff, 'writeoff')):
            if user.has_perm(f'spares.view_{name}'):
                entries = model.objects.filter(date__lte=today)
                context[f'{name}_count'] = entries.filter(date__gte=month_start).count()
                context[f'recent_{name}s'] = entries.select_related('spare', 'warehouse', 'measure').order_by(
                    '-date', '-pk',
                )[:5]
        return context


class WarehouseReportMixin(LoginRequiredMixin, PermissionRequiredMixin):
    context_object_name = 'report_data'


class FilteredReportView(WarehouseReportMixin, ListView):
    @cached_property
    def form(self):
        return self.form_class(self.request.GET or None)

    def get_queryset(self):
        if not self.form.is_valid():
            return self.model.objects.none()
        data = self.form.cleaned_data
        return (
            self.model.objects.filter(
                date__range=data['date_range'],
                **{self.model_field: data[self.form_field]},
            )
            .select_related(*self.related_fields)
            .order_by('-date', '-pk')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        context['report_title'] = self.report_title
        if self.form.is_valid():
            context['total_amount'] = self.object_list.aggregate(total=Sum(self.amount_field))['total']
        return context


class WriteOffReportView(FilteredReportView):
    model = WriteOff
    amount_field = 'total_amount'
    permission_required = 'spares.view_writeoff'
    template_name = 'spares/writeoff_report.html'
    related_fields = ('machine', 'trailer', 'worker', 'spare', 'measure', 'company', 'warehouse')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vehicle_field'] = self.model_field
        return context


class MachineReportView(WriteOffReportView):
    form_class = MachineReportForm
    form_field = 'machine'
    model_field = 'machine'
    report_title = 'Отчёт по технике'


class TrailerReportView(WriteOffReportView):
    form_class = TrailersReportForm
    form_field = 'trailers'
    model_field = 'trailer'
    report_title = 'Отчёт по прицепам'


class ContractorReportView(FilteredReportView):
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
    model = Stock
    queryset = Stock.objects.select_related('spare', 'measure', 'company', 'warehouse').order_by('spare__name', 'pk')
    permission_required = 'spares.view_stock'
    template_name = 'spares/stock_report.html'

    @cached_property
    def form(self):
        return StockFilterForm(self.request.GET or None)

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.form.is_bound:
            return queryset
        if not self.form.is_valid():
            return queryset.none()

        filters = self.form.cleaned_data
        if filters['q']:
            queryset = queryset.filter(spare__name__iregex=re.escape(filters['q']))
        if filters['warehouse']:
            queryset = queryset.filter(warehouse=filters['warehouse'])
        if filters['company']:
            queryset = queryset.filter(company=filters['company'])
        if filters['discrepancy']:
            queryset = queryset.filter(inventory__isnull=False, discrepancy=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.form
        context['counts'] = self.object_list.aggregate(
            matches=Count('pk'),
            discrepancies=Count('pk', filter=Q(inventory__isnull=False, discrepancy=True)),
            unavailable=Count('pk', filter=Q(actual_balance__lte=0)),
        )
        return context


class IncomeOutcomeReportView(WarehouseReportMixin, TemplateView):
    permission_required = ('spares.view_receipt', 'spares.view_writeoff')
    template_name = 'spares/income_outcome_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['income_report'] = get_income_report()
        context['outcome_report'] = get_outcome_report()
        context['months'] = ('Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек')
        return context
