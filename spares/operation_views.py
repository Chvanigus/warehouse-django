from re import escape

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import CreateView, DeleteView, ListView, RedirectView

from .forms import JournalFilterForm
from .models import Receipt, Stock, WriteOff


class OperationMixin(PermissionRequiredMixin):
    model = None
    permission_action = None
    list_title = ''

    @property
    def operation_name(self):
        return self.model._meta.model_name

    def permission_for(self, action):
        return f'spares.{action}_{self.operation_name}'

    def get_permission_required(self):
        return (self.permission_for(self.permission_action),)

    def get_success_url(self):
        if self.request.user.has_perm(self.permission_for('view')):
            return reverse(f'operations:{self.operation_name}s')
        return reverse('spares:warehouse_main')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['list_url'] = self.get_success_url()
        context['list_title'] = self.list_title
        context['operation_name'] = self.operation_name
        context['can_cancel'] = self.request.user.has_perm(self.permission_for('delete'))
        return context


class OperationJournalFilterForm(JournalFilterForm):
    entry = forms.IntegerField(
        label='Запись', min_value=1, max_value=2**63 - 1, required=False, widget=forms.HiddenInput,
    )


class OperationListView(OperationMixin, ListView):
    permission_action = 'view'
    paginate_by = 30
    context_object_name = 'entries'
    related_fields = ()
    order_by = ()
    search_fields = ()
    allow_add = True
    date_field = 'date'
    search_hint = ''
    add_label = ''
    add_route = None

    @cached_property
    def filters(self):
        form = OperationJournalFilterForm(self.request.GET or None)
        form.fields['q'].widget.attrs['placeholder'] = self.search_hint
        return form

    def get_queryset(self):
        queryset = super().get_queryset().select_related(*self.related_fields).order_by(*self.order_by)
        if not self.filters.is_bound:
            return queryset
        if not self.filters.is_valid():
            return queryset.none()
        data = self.filters.cleaned_data
        query = data['q']
        if query:
            # SQLite's case-insensitive LIKE only folds ASCII.
            pattern = escape(query)
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f'{field}__iregex': pattern})
            queryset = queryset.filter(filters)
        if data['date_from']:
            queryset = queryset.filter(**{f'{self.date_field}__gte': data['date_from']})
        if data['date_to']:
            queryset = queryset.filter(**{f'{self.date_field}__lte': data['date_to']})
        if data['entry']:
            queryset = queryset.filter(pk=data['entry'])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filters'] = self.filters
        context['today'] = timezone.localdate()
        context['filters_active'] = any(self.request.GET.get(name) for name in self.filters.fields)
        context['entry_id'] = self.filters.cleaned_data.get('entry') if self.filters.is_valid() else None
        if self.allow_add and self.request.user.has_perm(self.permission_for('add')):
            context['add_url'] = reverse(self.add_route or f'operations:{self.operation_name}_add')
            context['add_label'] = self.add_label
        context['cancel_route'] = f'operations:{self.operation_name}_cancel'
        return context


class OperationEditMixin(OperationMixin):
    template_name = 'spares/operations/form.html'

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Запись сохранена.')
        return response


class OperationCreateView(OperationEditMixin, CreateView):
    permission_action = 'add'

    def get_initial(self):
        initial = {**super().get_initial(), 'date': timezone.localdate()}
        if self.model is not WriteOff:
            return initial

        initial['quantity'] = None
        stock_id = self.request.GET.get('stock', '')
        if stock_id.isdecimal() and len(stock_id) <= 18:
            initial['spares_list'] = Stock.objects.filter(
                pk=int(stock_id), actual_balance__gt=0,
            ).values_list('pk', flat=True).first()
        return initial


class PostedOperationRedirectView(OperationMixin, RedirectView):
    permission_action = 'view'

    def get_redirect_url(self, *args, **kwargs):
        return self.get_success_url()


class OperationCancellationForm(forms.Form):
    reason = forms.CharField(
        label='Причина отмены', max_length=500,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
    )


class OperationCancelView(OperationMixin, DeleteView):
    permission_action = 'delete'
    template_name = 'spares/operations/delete.html'
    form_class = OperationCancellationForm
    http_method_names = ['get', 'head', 'post', 'options']

    def get_permission_required(self):
        return (self.permission_for('view'), self.permission_for('delete'))

    def get_queryset(self):
        entries = super().get_queryset().filter(cancelled_at__isnull=True)
        if self.model is Receipt:
            entries = entries.filter(invoice_id__isnull=True)
        return entries

    def form_valid(self, form):
        try:
            self.object.cancel(actor=self.request.user, reason=form.cleaned_data['reason'])
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Документ отменён. Запись сохранена в журнале.')
        return HttpResponseRedirect(self.get_success_url())
