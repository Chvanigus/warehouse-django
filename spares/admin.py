from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.db.models import Sum
from django.db.models.functions import TruncMonth

from .forms import WriteOffForm
from .models import *


@admin.register(Spares)
class SparesAdmin(admin.ModelAdmin):
    list_display = ['spare_name']


@admin.register(Warehouses)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['warehouse_name']


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['company_name']


@admin.register(Contractors)
class ContractorsAdmin(admin.ModelAdmin):
    list_display = ['contractor_name']


@admin.register(Workers)
class WorkersAdmin(admin.ModelAdmin):
    list_display = ['worker_name']


@admin.register(Machines)
class MachinesAdmin(admin.ModelAdmin):
    list_display = ['machine_name']


@admin.register(MachineWorker)
class MachineWorkerAdmin(admin.ModelAdmin):
    list_display = ('machine', 'worker')


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'spare',
        'company',
        'date',
        'warehouse',
        'quantity',
        'price',
        'amount',
        'invoice_number',
        'contractor'
    )
    list_filter = (
        'spare',
        'warehouse',
        'price',
        'company',
        'date'
    )
    readonly_fields = ['amount']


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_filter = ('spare', 'warehouse', 'price')
    list_display = ('spare', 'warehouse', 'input_quantity', 'output_quantity', 'actual_balance', 'price', 'plan',
                    'discrepancy', 'inventory')

    def has_change_permission(self, request, obj=None):
        return False


class WriteOffAdmin(admin.ModelAdmin):
    form = WriteOffForm
    list_display = (
        'spare',
        'company',
        'date',
        'machine',
        'worker',
        'warehouse',
        'quantity',
        'price',
        'total_amount'
    )
    list_filter = (
        'spare',
        'warehouse',
        'price',
        'company',
        'date',
        'machine',
        'worker'
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # Обработка зависимостей полей формы
        if request.method == 'POST' and 'spare' in request.POST:
            spare_id = request.POST['spare']
            stock = Stock.objects.filter(spare_id=spare_id).first()

            if stock:
                form.base_fields['warehouse'].disabled = False
                form.base_fields['price'].disabled = False
                form.base_fields['price'].choices = [(stock.price, stock.price)]
                form.base_fields['available_quantity'].initial = stock.actual_balance

        return form


class IncomeReportsAdmin(admin.ModelAdmin):
    list_display = [
        'company',
        'total_company',
        'january',
        'february',
        'march',
        'april',
        'may',
        'june',
        'july',
        'august',
        'september',
        'october',
        'november',
        'december'
    ]

    def has_change_permission(self, request, obj=None):
        return False


class OutcomeReportsAdmin(admin.ModelAdmin):
    list_display = [
        'company',
        'total_company',
        'january',
        'february',
        'march',
        'april',
        'may',
        'june',
        'july',
        'august',
        'september',
        'october',
        'november',
        'december'
    ]

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(IncomeReport, IncomeReportsAdmin)
admin.site.register(OutcomeReport, OutcomeReportsAdmin)
admin.site.register(WriteOff, WriteOffAdmin)
