from django.contrib import admin
from .forms import WriteOffForm, ReceiptForm
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
    list_display = ['contractor_name', 'contact', 'name']


@admin.register(Workers)
class WorkersAdmin(admin.ModelAdmin):
    list_display = ['worker_name']


@admin.register(Machines)
class MachinesAdmin(admin.ModelAdmin):
    list_display = ['machine_name']


@admin.register(MachineWorker)
class MachineWorkerAdmin(admin.ModelAdmin):
    list_display = ('worker', 'machine', 'trailer')


@admin.register(MeasureMeasurement)
class MeasureMeasurementAdmin(admin.ModelAdmin):
    list_display = ['measure_name']


@admin.register(Trailers)
class TrailersAdmin(admin.ModelAdmin):
    list_display = ['trailer_name']


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    form = ReceiptForm
    list_display = (
        'spare',
        'measure',
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


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_filter = ('spare', 'warehouse', 'price')
    list_display = (
        'spare',
        'measure',
        'company',
        'warehouse',
        'input_quantity',
        'output_quantity',
        'actual_balance',
        'price',
        'plan',
        'discrepancy',
        'inventory'
    )

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WriteOff)
class WriteOffAdmin(admin.ModelAdmin):
    form = WriteOffForm
    list_display = (
        'spare',
        'measure',
        'company',
        'date',
        'worker',
        'machine',
        'trailer',
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
