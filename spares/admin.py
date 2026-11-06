"""Настройки административных справочников и складских документов."""

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.actions import delete_selected
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils.translation import gettext_lazy as _

from .catalog_forms import ManualStockForm, StockCorrectionForm
from .forms import ReceiptForm, WriteOffForm
from .models import Spares, Warehouses, Company, Contractors, Workers, Machines, MachineWorker, MeasureMeasurement, \
    Trailers, Receipt, Stock, WriteOff, Movement
from .stock_adjustments import save_manual_stock


class StockOperationAdmin(admin.ModelAdmin):
    """Возвращает ошибки складских операций в интерфейс администрирования."""
    actions = ('delete_selected',)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Показывает причину отказа, если операция сохранения отклонена."""
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            return self.show_operation_error(request, error)

    def delete_view(self, request, object_id, extra_context=None):
        """Обрабатывает ошибки при запросе страницы удаления или подтверждении."""
        try:
            return super().delete_view(request, object_id, extra_context)
        except ValidationError as error:
            return self.show_operation_error(request, error)

    @admin.action(permissions=['delete'], description=_('Delete selected %(verbose_name_plural)s'))
    def delete_selected(self, request, queryset):
        """Удаляет выбранные записи в одной транзакции и сообщает об отказе."""
        try:
            with transaction.atomic(using=queryset.db):
                return delete_selected(self, request, queryset)
        except ValidationError as error:
            return self.show_operation_error(request, error)

    def show_operation_error(self, request, error):
        """Записывает ошибку в уведомления и возвращает пользователя на текущую страницу."""
        self.message_user(request, ' '.join(error.messages), level=messages.ERROR)
        return HttpResponseRedirect(request.get_full_path())


class PostedOperationAdmin(StockOperationAdmin):
    """Разрешает просматривать проведённый документ в админке."""
    def has_add_permission(self, request):
        """Проверяет право прямого проведения, чтобы оператор не обошёл очередь заявок."""
        return request.user.has_perm('spares.approve_stockrequest') and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        """Запрещает редактировать проведённые документы в админке."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрещает физическое удаление проведённых документов."""
        return False


@admin.register(Spares)
class SparesAdmin(admin.ModelAdmin):
    """Настраивает список и поиск запчастей по названию и артикулу."""
    list_display = ('name', 'sku')
    search_fields = ('name', 'sku')


@admin.register(Warehouses)
class WarehouseAdmin(admin.ModelAdmin):
    """Настраивает список и поиск складов по названию."""
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    """Настраивает список и поиск фирм по названию."""
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Contractors)
class ContractorsAdmin(admin.ModelAdmin):
    """Настраивает поиск контрагентов по названию и контактному лицу."""
    list_display = ('name', 'contact', 'contact_name')
    search_fields = ('name', 'contact_name')


@admin.register(Workers)
class WorkersAdmin(admin.ModelAdmin):
    """Настраивает список работников для поиска по имени."""
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Machines)
class MachinesAdmin(admin.ModelAdmin):
    """Настраивает список и поиск техники."""
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(MachineWorker)
class MachineWorkerAdmin(admin.ModelAdmin):
    """Показывает назначения работников и поиск по связанным справочникам."""
    list_display = ('worker', 'machine', 'trailer')
    autocomplete_fields = ('worker', 'machine', 'trailer')
    search_fields = ('worker__name', 'machine__name', 'trailer__name')
    list_select_related = ('worker', 'machine', 'trailer')


@admin.register(MeasureMeasurement)
class MeasureMeasurementAdmin(admin.ModelAdmin):
    """Настраивает список единиц измерения."""
    list_display = ('name',)


@admin.register(Trailers)
class TrailersAdmin(admin.ModelAdmin):
    """Настраивает список прицепов и поиск по названию."""
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Receipt)
class ReceiptAdmin(PostedOperationAdmin):
    """Показывает приход с реквизитами накладной, складом и суммой."""
    form = ReceiptForm
    list_display = (
        'spare',
        'measure',
        'quantity',
        'price',
        'amount',
        'company',
        'date',
        'warehouse',
        'invoice_number',
        'contractor'
    )
    list_filter = (
        'date',
        'warehouse',
        'company',
        'contractor'
    )
    search_fields = ('spare__name',)
    autocomplete_fields = ('spare', 'company', 'contractor', 'warehouse')
    readonly_fields = ('amount',)
    list_select_related = ('spare', 'measure', 'company', 'warehouse', 'contractor')


@admin.register(Stock)
class StockAdmin(StockOperationAdmin):
    """Настраивает просмотр и ручную корректировку складских остатков."""
    form = ManualStockForm
    list_filter = ('warehouse', 'company')
    list_display = (
        'spare',
        'actual_balance',
        'input_quantity',
        'output_quantity',
        'measure',
        'company',
        'warehouse',
        'price',
        'plan',
        'discrepancy',
        'inventory'
    )
    search_fields = ('spare__name',)
    readonly_fields = (
        'input_quantity',
        'output_quantity',
        'discrepancy',
        'inventory',
        'inventory_book_balance',
    )
    autocomplete_fields = ('spare', 'warehouse', 'company')
    list_select_related = ('spare', 'measure', 'company', 'warehouse')

    def has_delete_permission(self, request, obj=None):
        """Запрещает удалять остатки через административную форму."""
        return False

    def get_form(self, request, obj=None, **kwargs):
        """Выбирает ввод начального остатка или корректировку с проверкой версии."""
        kwargs['form'] = StockCorrectionForm if obj is not None else ManualStockForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        """Сохраняет остаток с причиной и автором через общий сервис корректировок."""
        save_manual_stock(obj, actor=request.user, reason=form.cleaned_data['reason'])


@admin.register(WriteOff)
class WriteOffAdmin(PostedOperationAdmin):
    """Настраивает создание списаний и просмотр проведённых документов."""
    form = WriteOffForm
    list_display = (
        'spare',
        'measure',
        'quantity',
        'price',
        'total_amount',
        'company',
        'date',
        'worker',
        'machine',
        'trailer',
        'warehouse',
    )
    list_filter = (
        'warehouse',
        'company',
        'date',
    )

    search_fields = ('spare__name',)
    readonly_fields = ('total_amount',)
    list_select_related = ('spare', 'measure', 'company', 'warehouse', 'worker', 'machine', 'trailer')

    class Media:
        """Подключает локальные ресурсы для поиска в полях списания."""
        css = {'all': ('admin/css/vendor/select2/select2.min.css',)}
        js = (
            'admin/js/vendor/jquery/jquery.js' if settings.DEBUG else 'admin/js/vendor/jquery/jquery.min.js',
            'admin/js/vendor/select2/select2.full.min.js',
            'admin/js/vendor/select2/i18n/ru.js',
            'admin/js/jquery.init.js',
            'js/pages/warehouse-choice.js',
        )


@admin.register(Movement)
class MovementAdmin(admin.ModelAdmin):
    """Показывает прежний журнал перемещений в режиме просмотра."""
    list_display = ('spare', 'from_warehouse', 'to_warehouse', 'timestamp')
    search_fields = ('spare__name',)
    list_filter = ('timestamp',)
    list_select_related = ('spare', 'from_warehouse', 'to_warehouse')

    def has_add_permission(self, request):
        """Запрещает создание записей в прежнем журнале."""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещает редактирование исторических перемещений."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрещает удаление исторических перемещений."""
        return False
