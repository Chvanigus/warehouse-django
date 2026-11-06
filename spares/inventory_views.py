"""Страницы записи фактического количества и истории инвентаризационных пересчётов."""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import FormView, ListView

from .catalog_forms import STOCK_REVISION_SALT, validate_stock_version
from .forms import StockJournalFilterForm
from .inventory_counts import record_inventory_count
from .inventory_sheet_models import InventorySheet
from .models import InventoryCount, Stock
from .permission_views import CurrentPermissionPostMixin
from .stock_adjustments import stock_version


class InventoryCountForm(forms.Form):
    """Принимает результат пересчёта и защищает форму от устаревшего остатка."""
    counted_quantity = forms.DecimalField(
        label='Количество по факту', min_value=Decimal('0.00'), max_digits=15, decimal_places=2,
    )
    note = forms.CharField(
        label='Примечание', required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
    )
    revision = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, stock, **kwargs):
        """Подписывает состояние остатка перед открытием формы пересчёта."""
        super().__init__(*args, **kwargs)
        self.stock_revision = stock_version(stock)
        self.initial['revision'] = signing.dumps(self.stock_revision, salt=STOCK_REVISION_SALT)

    def clean_revision(self):
        """Сравнивает присланную версию остатка с актуальной."""
        return validate_stock_version(self.cleaned_data['revision'], self.stock_revision)


class InventoryCountCreateView(CurrentPermissionPostMixin, LoginRequiredMixin, PermissionRequiredMixin, FormView):
    """Записывает фактическое количество для выбранной складской позиции."""
    permission_required = 'spares.add_inventorycount'
    template_name = 'spares/inventory/form.html'
    form_class = InventoryCountForm

    @cached_property
    def stock(self):
        """Загружает складскую позицию и связанные реквизиты либо возвращает 404."""
        return get_object_or_404(
            Stock.objects.select_related('spare', 'warehouse', 'company', 'measure'),
            pk=self.kwargs['pk'],
        )

    def get_form_kwargs(self):
        """Передаёт форме позицию для подписи и проверки её версии."""
        return {**super().get_form_kwargs(), 'stock': self.stock}

    def get_context_data(self, **kwargs):
        """Передаёт выбранную складскую позицию в шаблон пересчёта."""
        return super().get_context_data(stock=self.stock, **kwargs)

    def form_valid(self, form):
        """Записывает пересчёт через сервис и выбирает доступную страницу возврата."""
        try:
            record_inventory_count(
                self.stock, actor=self.request.user, counted_quantity=form.cleaned_data['counted_quantity'],
                note=form.cleaned_data['note'],
            )
        except ValidationError as error:
            form.add_error(None, error.messages)
            return self.form_invalid(form)
        messages.success(self.request, 'Результат пересчёта записан.')
        if self.request.user.has_perm('spares.view_inventorycount'):
            return redirect(reverse('inventory:list', query={'stock': self.stock.pk}))
        if self.request.user.has_perm('spares.view_stock'):
            return redirect('spares:stock_report')
        return redirect('spares:warehouse_main')


class InventoryCountListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Показывает постраничную историю пересчётов и связь с ведомостью."""
    model = InventoryCount
    queryset = InventoryCount.objects.select_related('sheet_line__sheet')
    permission_required = 'spares.view_inventorycount'
    template_name = 'spares/inventory/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    @cached_property
    def filters(self):
        """Создаёт форму поиска по истории пересчётов."""
        return StockJournalFilterForm(self.request.GET or None, search_hint='Запчасть, склад, автор или примечание')

    def get_queryset(self):
        """Ограничивает историю указанной позицией, текстом поиска и диапазоном дат."""
        queryset = super().get_queryset()
        if not self.request.user.has_perm('spares.approve_inventorysheet'):
            queryset = queryset.filter(
                Q(sheet_line__isnull=True)
                | Q(sheet_line__sheet__status=InventorySheet.Status.APPROVED)
                | Q(sheet_line__sheet__created_by=self.request.user),
            )
        return self.filters.filter_queryset(
            queryset, search_fields=('stock_label', 'actor_name', 'note'),
            date_field='counted_at__date', exact_fields=(('stock', 'stock_id'),),
        )

    def get_context_data(self, **kwargs):
        """Передаёт форму и выбранную складскую позицию в контекст журнала."""
        return super().get_context_data(
            filters=self.filters,
            stock_id=self.filters.cleaned_data.get('stock') if self.filters.is_valid() else None,
            **kwargs,
        )
