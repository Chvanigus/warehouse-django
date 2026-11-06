"""Представления журналов, проведения и отмены прихода и списания."""

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import CreateView, DeleteView, ListView, RedirectView

from .forms import JournalFilterForm
from .models import Receipt, Stock, WriteOff
from .request_models import StockRequest
from .request_operations import assignment_snapshot, serialize_form_data
from .request_services import submit_stock_request


def redirect_to_pending_request(request, stock_request, fallback_url):
    """Сообщает о подаче и открывает доступную пользователю страницу."""
    messages.success(request, 'Заявка отправлена на согласование.')
    if request.user.has_perm('spares.view_stockrequest'):
        return redirect('stock_requests:detail', pk=stock_request.pk)
    return HttpResponseRedirect(fallback_url)


class OperationMixin(PermissionRequiredMixin):
    """Связывает модель операции с правами, названием журнала и адресом возврата."""
    model = None
    permission_action = None
    list_title = ''

    @property
    def operation_name(self):
        """Возвращает имя модели, используемое в маршрутах и кодах прав."""
        return self.model._meta.model_name

    def permission_for(self, action):
        """Формирует код права Django для действия над операцией."""
        return f'spares.{action}_{self.operation_name}'

    def get_permission_required(self):
        """Требует право на действие, заданное конкретным представлением."""
        return (self.permission_for(self.permission_action),)

    def get_success_url(self):
        """Выбирает журнал операции или главную страницу согласно правам."""
        if self.request.user.has_perm(self.permission_for('view')):
            return reverse(f'operations:{self.operation_name}s')
        return reverse('spares:warehouse_main')

    def get_context_data(self, **kwargs):
        """Передаёт название журнала, ссылку возврата и возможность отмены."""
        context = super().get_context_data(**kwargs)
        context['list_url'] = self.get_success_url()
        context['list_title'] = self.list_title
        context['operation_name'] = self.operation_name
        context['can_cancel'] = self.request.user.has_perm(self.permission_for('delete'))
        return context


class OperationJournalFilterForm(JournalFilterForm):
    """Дополняет диапазон дат точным фильтром по номеру записи."""
    entry = forms.IntegerField(
        label='Запись', min_value=1, max_value=2**63 - 1, required=False, widget=forms.HiddenInput,
    )


class OperationListView(OperationMixin, ListView):
    """Показывает журнал выбранной складской операции с поиском и навигацией."""
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
        """Строит форму поиска с подсказкой для конкретного типа операции."""
        return OperationJournalFilterForm(self.request.GET or None, search_hint=self.search_hint)

    def get_queryset(self):
        """Загружает строки со связанными реквизитами и применяет фильтры."""
        queryset = super().get_queryset().select_related(*self.related_fields).order_by(*self.order_by)
        return self.filters.filter_queryset(
            queryset, search_fields=self.search_fields, date_field=self.date_field, exact_fields=(('entry', 'pk'),),
        )

    def get_context_data(self, **kwargs):
        """Передаёт шаблону текущую дату, фильтры и доступные операции."""
        context = super().get_context_data(**kwargs)
        context['filters'] = self.filters
        context['today'] = timezone.localdate()
        context['filters_active'] = any(self.request.GET.get(name) for name in self.filters.fields)
        context['entry_id'] = self.filters.cleaned_data.get('entry') if self.filters.is_valid() else None
        if self.allow_add and self.request.user.has_perms((self.permission_for('add'), 'spares.add_stockrequest')):
            context['add_url'] = reverse(self.add_route or f'operations:{self.operation_name}_add')
            context['add_label'] = (
                self.add_label if self.request.user.has_perm('spares.approve_stockrequest') else 'Подать заявку'
            )
        context['cancel_route'] = f'operations:{self.operation_name}_cancel'
        return context


class OperationEditMixin(OperationMixin):
    """Передаёт данные формы на согласование или немедленное проведение."""
    template_name = 'spares/operations/form.html'

    def post(self, request, *args, **kwargs):
        """Объединяет проверку формы и подачу заявки в одну транзакцию."""
        with transaction.atomic():
            return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """Фиксирует реквизиты заявки и возвращает пользователя к её результату."""
        payload = serialize_form_data(form.cleaned_data)
        if self.model is WriteOff:
            payload['assignment'] = assignment_snapshot(form.cleaned_data['machine_list'])
            title = f'Списание · {form.cleaned_data["spares_list"].spare}'
        else:
            title = f'Приход по накладной № {form.cleaned_data["invoice_number"]}'
        try:
            stock_request = submit_stock_request(
                self.operation_name, payload, actor=self.request.user, title=title,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        if stock_request.status == StockRequest.Status.PENDING:
            return redirect_to_pending_request(self.request, stock_request, self.get_success_url())
        messages.success(self.request, 'Запись сохранена.')
        return HttpResponseRedirect(self.get_success_url())


class OperationCreateView(OperationEditMixin, CreateView):
    """Принимает заявку на приход или списание с проверкой права добавления."""
    permission_action = 'add'

    def get_permission_required(self):
        """Требует право на вид операции и подачу складской заявки."""
        return (*super().get_permission_required(), 'spares.add_stockrequest')

    def get_initial(self):
        """Подставляет текущую дату и при списании выбирает доступный остаток по ссылке."""
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
    """Перенаправляет со старого адреса редактирования проведённой операции."""
    permission_action = 'view'

    def get_redirect_url(self, *args, **kwargs):
        """Возвращает адрес журнала, если пользователю разрешён его просмотр."""
        return self.get_success_url()


class OperationCancellationForm(forms.Form):
    """Запрашивает обязательную причину отмены документа."""
    reason = forms.CharField(
        label='Причина отмены', max_length=500,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
    )


class OperationCancelView(OperationMixin, DeleteView):
    """Отменяет проведённый документ с сохранением записи в журнале."""
    permission_action = 'delete'
    template_name = 'spares/operations/delete.html'
    form_class = OperationCancellationForm
    http_method_names = ['get', 'head', 'post', 'options']

    def get_permission_required(self):
        """Требует одновременно просмотр и право отмены документа."""
        return (self.permission_for('view'), self.permission_for('delete'))

    def get_queryset(self):
        """Исключает отменённые документы и строки накладных, отменяемые только вместе."""
        entries = super().get_queryset().filter(cancelled_at__isnull=True)
        if self.model is Receipt:
            entries = entries.filter(invoice_id__isnull=True)
        return entries

    def form_valid(self, form):
        """Отменяет операцию и возвращает пользователя в журнал либо к ошибке формы."""
        try:
            self.object.cancel(actor=self.request.user, reason=form.cleaned_data['reason'])
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Документ отменён. Запись сохранена в журнале.')
        return HttpResponseRedirect(self.get_success_url())
