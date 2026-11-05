from re import escape

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, ListView, UpdateView


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
        context['object_label'] = self.model._meta.verbose_name
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

    def get_queryset(self):
        queryset = super().get_queryset().select_related(*self.related_fields).order_by(*self.order_by)
        query = self.request.GET.get('q', '').strip()[:100]
        if query:
            # SQLite's case-insensitive LIKE only folds ASCII.
            pattern = escape(query)
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f'{field}__iregex': pattern})
            queryset = queryset.filter(filters)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('q', '').strip()[:100]
        if self.allow_add and self.request.user.has_perm(self.permission_for('add')):
            context['add_url'] = reverse(f'operations:{self.operation_name}_add')
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
