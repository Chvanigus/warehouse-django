"""Views приложения spares."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.views.generic import ListView, TemplateView

from spares.forms import MachineReportForm, TrailersReportForm
from spares.models import WriteOff, Stock
from spares.utils import get_date_range, get_date_range_from_form


class WarehouseMainView(LoginRequiredMixin, TemplateView):
    """Главная страница."""
    template_name = 'warehouse/index.html'


class MachineReportView(LoginRequiredMixin, ListView):
    model = WriteOff
    template_name = 'spares/machine_report.html'
    context_object_name = 'report_data'
    form_class = MachineReportForm

    def get_queryset(self):
        machine = self.request.GET.get('machine')
        date_range = get_date_range_from_form(self.request)

        if date_range and machine:
            queryset = WriteOff.objects.filter(
                machine=machine,
                date__range=date_range
            )
        else:
            queryset = None
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.get_form()
        queryset = self.get_queryset()
        if queryset:
            context['total_amount'] = queryset.aggregate(total_amount=Sum('total_amount')).get('total_amount')
        return context

    def get_form(self):
        form = self.form_class(self.request.GET)
        return form


class TrailerReportView(LoginRequiredMixin, ListView):
    model = WriteOff
    template_name = 'spares/trailer_report.html'
    context_object_name = 'report_data'
    form_class = TrailersReportForm

    def get_queryset(self):
        trailer = self.request.GET.get('trailers')
        date_range = get_date_range_from_form(self.request)

        if date_range and trailer:
            queryset = WriteOff.objects.filter(
                trailer=trailer,
                date__range=date_range
            )
        else:
            queryset = None
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.get_form()
        queryset = self.get_queryset()
        if queryset:
            context['total_amount'] = queryset.aggregate(total_amount=Sum('total_amount')).get('total_amount')
        return context

    def get_form(self):
        form = self.form_class(self.request.GET)
        return form


class StockReportView(LoginRequiredMixin, ListView):
    model = Stock
    template_name = 'spares/stock_report.html'
    context_object_name = 'report_data'

