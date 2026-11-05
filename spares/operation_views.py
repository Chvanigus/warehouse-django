from re import escape

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import JournalFilterForm
from .models import Stock, WriteOff


class OperationMixin(PermissionRequiredMixin):
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
        context['can_change'] = self.request.user.has_perm(self.permission_for('change'))
        context['can_delete'] = self.request.user.has_perm(self.permission_for('delete'))
        return context


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

    @cached_property
    def filters(self):
        form = JournalFilterForm(self.request.GET or None)
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
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filters'] = self.filters
        context['filters_active'] = any(self.request.GET.get(name) for name in self.filters.fields)
        if self.allow_add and self.request.user.has_perm(self.permission_for('add')):
            context['add_url'] = reverse(f'operations:{self.operation_name}_add')
            context['add_label'] = self.add_label
        context['edit_route'] = f'operations:{self.operation_name}_edit'
        context['delete_route'] = f'operations:{self.operation_name}_delete'
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


class OperationUpdateView(OperationEditMixin, UpdateView):
    permission_action = 'change'


class OperationDeleteView(OperationMixin, DeleteView):
    permission_action = 'delete'
    template_name = 'spares/operations/delete.html'
    http_method_names = ['get', 'head', 'post', 'options']

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Запись удалена.')
        return response
