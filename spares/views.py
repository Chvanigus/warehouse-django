import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.views.generic import ListView, TemplateView

from spares.forms import MachineReportForm
from spares.models import WriteOff, Machines


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
        date_str = self.request.GET.get('month')

        month_names = {
            "Январь": 1,
            "Февраль": 2,
            "Март": 3,
            "Апрель": 4,
            "Май": 5,
            "Июнь": 6,
            "Июль": 7,
            "Август": 8,
            "Сентябрь": 9,
            "Октябрь": 10,
            "Ноябрь": 11,
            "Декабрь": 12
        }

        if date_str and machine:
            month_name, year_str = date_str.split()
            year = int(year_str)
            month = month_names[month_name]
            selected_month_year = datetime.datetime(year, month, 1)

            queryset = WriteOff.objects.filter(
                machine=machine,
                date__month=selected_month_year.month,
                date__year=selected_month_year.year
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

