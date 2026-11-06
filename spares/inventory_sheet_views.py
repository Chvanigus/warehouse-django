"""Рабочие страницы составления и проверки инвентаризационных ведомостей."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView

from .inventory_sheet_forms import (
    InventorySheetForm,
    InventorySheetFormSet,
    InventorySheetReviewForm,
    WarehouseSelectionForm,
)
from .inventory_sheet_models import InventorySheet, InventorySheetLine
from .inventory_sheet_services import review_inventory_sheet, submit_inventory_sheet
from .models import Stock
from .stock_adjustments import stock_version


SNAPSHOT_SALT = 'spares.inventory-sheet.snapshot.v1'


class InventorySheetListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Показывает список ведомостей с количеством позиций и состоянием проверки."""
    permission_required = 'spares.view_inventorysheet'
    template_name = 'spares/inventory_sheets/list.html'
    context_object_name = 'sheets'
    paginate_by = 30
    queryset = InventorySheet.objects.select_related('warehouse').annotate(
        line_count=Count('lines'),
    ).order_by('-created_at', '-pk')


class InventorySheetAddView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Принимает результаты пересчёта нескольких позиций одного склада."""
    permission_required = 'spares.add_inventorysheet'
    template_name = 'spares/inventory_sheets/add.html'

    def stocks(self, warehouse):
        """Выбирает позиции указанного склада с данными для подписей в форме."""
        return (
            Stock.objects.filter(warehouse=warehouse)
            .select_related('spare', 'warehouse', 'company', 'measure')
            .order_by('spare__name', 'pk')
        )

    def line_forms(self, stocks, options, data=None):
        """Строит набор строк ведомости с ограниченным списком остатков."""
        return InventorySheetFormSet(data, form_kwargs={
            'stocks': stocks, 'choices': [('', 'Выберите позицию'), *((stock.pk, str(stock)) for stock in options)],
        })

    def get(self, request):
        """Открывает выбор склада или форму с подписанным снимком остатков."""
        chooser = WarehouseSelectionForm(request.GET or None, auto_id='choose_%s')
        if not chooser.is_valid():
            return render(request, self.template_name, {'chooser': chooser})
        warehouse = chooser.cleaned_data['warehouse']
        stocks = self.stocks(warehouse)
        options = list(stocks)
        snapshot = signing.dumps({
            'actor': str(request.user.pk),
            'warehouse': warehouse.pk,
            'stocks': {str(stock.pk): stock_version(stock) for stock in options},
        }, salt=SNAPSHOT_SALT, compress=True)
        return render(request, self.template_name, {
            'chooser': chooser, 'warehouse': warehouse, 'has_stocks': bool(options),
            'form': InventorySheetForm(initial={'warehouse': warehouse.pk, 'snapshot': snapshot}),
            'lines': self.line_forms(stocks, options),
        })

    def post(self, request):
        """Проверяет автора, снимок и строки, затем сохраняет ведомость через сервис."""
        chooser = WarehouseSelectionForm(request.POST, auto_id='choose_%s')
        form = InventorySheetForm(request.POST)
        if not chooser.is_valid():
            return render(request, self.template_name, {'chooser': chooser})
        warehouse = chooser.cleaned_data['warehouse']
        stocks = self.stocks(warehouse)
        options = list(stocks)
        lines = self.line_forms(stocks, options, request.POST)
        if form.is_valid() and lines.is_valid():
            try:
                snapshot = signing.loads(form.cleaned_data['snapshot'], salt=SNAPSHOT_SALT)
                if snapshot['actor'] != str(request.user.pk) or snapshot['warehouse'] != warehouse.pk:
                    raise signing.BadSignature
                sheet = submit_inventory_sheet(
                    warehouse=warehouse, actor=request.user, entries=lines.entries(), note=form.cleaned_data['note'],
                    expected_versions=snapshot['stocks'],
                )
            except signing.BadSignature:
                form.add_error(None, 'Форма устарела. Загрузите актуальные данные.')
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Ведомость передана контролёру.')
                if request.user.has_perm('spares.view_inventorysheet'):
                    return redirect('inventory_sheets:detail', pk=sheet.pk)
                return redirect('spares:warehouse_main')
        return render(request, self.template_name, {
            'chooser': chooser, 'warehouse': warehouse, 'has_stocks': bool(options),
            'form': form, 'lines': lines,
        })


def sheet_details():
    """Подготавливает ведомость со строками пересчёта и связанными корректировками."""
    return InventorySheet.objects.select_related('warehouse').prefetch_related(
        Prefetch('lines', queryset=InventorySheetLine.objects.select_related('count', 'adjustment')),
    )


def can_review(user, sheet):
    """Проверяет состояние ведомости, право проверки и отличие контролёра от автора."""
    return (
        sheet.status == InventorySheet.Status.PENDING
        and sheet.created_by_id != user.pk
        and user.has_perm('spares.approve_inventorysheet')
    )


class InventorySheetDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Показывает ведомость и доступные контролёру действия."""
    permission_required = 'spares.view_inventorysheet'
    template_name = 'spares/inventory_sheets/detail.html'
    context_object_name = 'sheet'

    def get_queryset(self):
        """Загружает ведомость вместе со строками и корректировками."""
        return sheet_details()

    def get_context_data(self, **kwargs):
        """Передаёт форму проверки и признак доступности действия."""
        return super().get_context_data(
            review_form=InventorySheetReviewForm(), can_review=can_review(self.request.user, self.object), **kwargs,
        )


class InventorySheetReviewView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Обрабатывает решение контролёра о подтверждении или отклонении ведомости."""
    permission_required = ('spares.view_inventorysheet', 'spares.approve_inventorysheet')

    def post(self, request, pk):
        """Передаёт решение в сервис и показывает результат либо ошибки проверки."""
        sheet = get_object_or_404(sheet_details(), pk=pk)
        form = InventorySheetReviewForm(request.POST)
        if form.is_valid():
            approve = form.cleaned_data['decision'] == 'approve'
            try:
                review_inventory_sheet(sheet, actor=request.user, approve=approve, note=form.cleaned_data['note'])
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Ведомость подтверждена.' if approve else 'Ведомость отклонена.')
                return redirect('inventory_sheets:detail', pk=sheet.pk)
        return render(request, 'spares/inventory_sheets/detail.html', {
            'sheet': sheet, 'review_form': form, 'can_review': can_review(request.user, sheet),
        })
