from decimal import Decimal
from re import escape

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import FormView, ListView

from .catalog_forms import STOCK_REVISION_SALT, stock_version, validate_stock_version
from .forms import StockJournalFilterForm
from .inventory_counts import record_inventory_count
from .models import InventoryCount, Stock


class InventoryCountForm(forms.Form):
    counted_quantity = forms.DecimalField(
        label='Количество по факту', min_value=Decimal('0.00'), max_digits=15, decimal_places=2,
    )
    note = forms.CharField(
        label='Примечание', required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
    )
    revision = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, stock, **kwargs):
        super().__init__(*args, **kwargs)
        self.stock_revision = stock_version(stock)
        self.initial['revision'] = signing.dumps(self.stock_revision, salt=STOCK_REVISION_SALT)

    def clean_revision(self):
        return validate_stock_version(self.cleaned_data['revision'], self.stock_revision)


class InventoryCountCreateView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    permission_required = 'spares.add_inventorycount'
    template_name = 'spares/inventory/form.html'
    form_class = InventoryCountForm

    @cached_property
    def stock(self):
        return get_object_or_404(Stock.objects.select_related('spare', 'warehouse', 'company', 'measure'),
                                 pk=self.kwargs['pk'])

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'stock': self.stock}

    def get_context_data(self, **kwargs):
        return super().get_context_data(stock=self.stock, **kwargs)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
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
    model = InventoryCount
    queryset = InventoryCount.objects.select_related('sheet_line__sheet')
    permission_required = 'spares.view_inventorycount'
    template_name = 'spares/inventory/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    @cached_property
    def filters(self):
        form = StockJournalFilterForm(self.request.GET or None)
        form.fields['q'].widget.attrs['placeholder'] = 'Запчасть, склад, автор или примечание'
        return form

    def get_queryset(self):
        entries = super().get_queryset()
        if not self.filters.is_bound:
            return entries
        if not self.filters.is_valid():
            return entries.none()
        data = self.filters.cleaned_data
        if data['q']:
            pattern = escape(data['q'])
            entries = entries.filter(
                Q(stock_label__iregex=pattern) | Q(actor_name__iregex=pattern) | Q(note__iregex=pattern),
            )
        if data['date_from']:
            entries = entries.filter(counted_at__date__gte=data['date_from'])
        if data['date_to']:
            entries = entries.filter(counted_at__date__lte=data['date_to'])
        if data['stock']:
            entries = entries.filter(stock_id=data['stock'])
        return entries

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            filters=self.filters,
            stock_id=self.filters.cleaned_data.get('stock') if self.filters.is_valid() else None,
            **kwargs,
        )
