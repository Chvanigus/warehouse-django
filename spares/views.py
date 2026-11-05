"""Views for the warehouse dashboard and reports."""
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Sum
from django.utils.functional import cached_property
from django.views.generic import ListView, TemplateView

from spares.context_processors.income_outcome_report import get_income_report, get_outcome_report
from spares.models import Receipt, Stock, WriteOff
from spares.report_forms import ContractorsReportForm, MachineReportForm, TrailersReportForm


class WarehouseMainView(LoginRequiredMixin, TemplateView):
    template_name = 'warehouse/index.html'


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


class IncomeOutcomeReportView(WarehouseReportMixin, TemplateView):
    permission_required = ('spares.view_receipt', 'spares.view_writeoff')
    template_name = 'spares/income_outcome_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['income_report'] = get_income_report()
        context['outcome_report'] = get_outcome_report()
        context['months'] = ('Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек')
        return context
