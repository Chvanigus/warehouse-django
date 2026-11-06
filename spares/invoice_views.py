"""Страницы накладных, загрузки XLSX, подтверждения проведения и отмены."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import JournalFilterForm
from .invoice_forms import InvoiceCancelForm, InvoiceHeaderForm, InvoiceLineForm, InvoiceLineFormSet, InvoiceUploadForm
from .invoice_models import ReceiptInvoice
from .invoice_services import cancel_receipt_invoice, invoice_version
from .invoice_xlsx import make_invoice_workbook, read_invoice_workbook
from .models import Receipt
from .operation_views import redirect_to_pending_request
from .request_models import StockRequest
from .request_operations import serialize_form_data
from .request_services import submit_stock_request


HEADER_FIELDS = tuple(InvoiceHeaderForm.base_fields)
PREVIEW_SALT = 'warehouse.receipt-invoice.v1'
PREVIEW_MAX_AGE = 20 * 60


def _prepare_preview(actor, header, lines):
    """Подписывает предпросмотр с автором и версией накладной для безопасного подтверждения."""
    return signing.dumps({
        'user': str(actor.pk),
        'version': invoice_version(header, ReceiptInvoice.normalize_number(header['number'])),
        'header': serialize_form_data(header),
        'lines': [serialize_form_data(line) for line in lines],
    }, salt=PREVIEW_SALT, compress=True)


def _header_values(form):
    """Выделяет проверенные реквизиты накладной из данных формы."""
    return {name: form.cleaned_data[name] for name in HEADER_FIELDS}


class InvoicePermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Подключает проверку прав и общий сценарий подачи накладной."""
    def redirect_after_posting(self, invoice_id):
        """Открывает проведённую накладную или главную страницу согласно правам."""
        if self.request.user.has_perm('spares.view_receipt'):
            return redirect('invoices:detail', pk=invoice_id)
        return redirect('spares:warehouse_main')

    def post_invoice(self, header, lines, error_form, *, preview_version=None, preview_key=None):
        """Подаёт накладную и защищает предпросмотр XLSX от повторной отправки."""
        payload = {'header': serialize_form_data(header), 'lines': [serialize_form_data(line) for line in lines]}
        if preview_version is not None:
            payload.update(preview_version=preview_version, preview_key=preview_key)
        try:
            with transaction.atomic():
                if preview_version is not None:
                    number_key = ReceiptInvoice.normalize_number(header['number'])
                    if invoice_version(header, number_key) != preview_version:
                        raise ValidationError(
                            'История этой накладной изменилась. Загрузите файл для нового предпросмотра.',
                        )
                    if StockRequest.objects.filter(
                        kind=StockRequest.Kind.RECEIPT_INVOICE, payload__preview_key=preview_key,
                    ).exists():
                        raise ValidationError('Заявка по этому предпросмотру уже существует.')
                stock_request = submit_stock_request(
                    StockRequest.Kind.RECEIPT_INVOICE, payload, actor=self.request.user,
                    title=f'Накладная № {header["number"]}',
                )
        except ValidationError as error:
            error_form.add_error(None, error)
        else:
            if stock_request.status == StockRequest.Status.PENDING:
                destination = 'invoices:list' if self.request.user.has_perm('spares.view_receipt') else 'spares:warehouse_main'
                return redirect_to_pending_request(self.request, stock_request, reverse(destination))
            messages.success(self.request, 'Накладная проведена.')
            return self.redirect_after_posting(stock_request.result['pk'])
        return None


class InvoiceListView(InvoicePermissionMixin, ListView):
    """Выводит накладные с числом строк и итоговой суммой."""
    permission_required = 'spares.view_receipt'
    template_name = 'spares/invoices/list.html'
    context_object_name = 'invoices'
    paginate_by = 30
    queryset = ReceiptInvoice.objects.select_related('company', 'contractor', 'warehouse').annotate(
        line_count=Count('lines'), total=Sum('lines__amount'),
    ).order_by('-date', '-pk')

    @cached_property
    def filters(self):
        """Подготавливает фильтры по номеру, поставщику и датам."""
        return JournalFilterForm(self.request.GET or None, search_hint='Номер или поставщик')

    def get_queryset(self):
        """Ограничивает список накладных по реквизитам и периоду."""
        return self.filters.filter_queryset(super().get_queryset(), search_fields=('number', 'contractor__name'))

    def get_context_data(self, **kwargs):
        """Добавляет форму фильтров в контекст списка накладных."""
        return super().get_context_data(filters=self.filters, **kwargs)


class InvoiceDetailView(InvoicePermissionMixin, DetailView):
    """Показывает накладную с реквизитами и строками в исходном порядке."""
    permission_required = 'spares.view_receipt'
    template_name = 'spares/invoices/detail.html'
    context_object_name = 'invoice'
    queryset = ReceiptInvoice.objects.select_related('company', 'contractor', 'warehouse').prefetch_related(
        Prefetch('lines', queryset=Receipt.objects.select_related('spare', 'measure').order_by('pk')),
    ).annotate(total=Sum('lines__amount'))


class InvoiceAddView(InvoicePermissionMixin, View):
    """Принимает накладную, заполненную вручную на сайте."""
    permission_required = ('spares.add_receipt', 'spares.add_stockrequest')
    template_name = 'spares/invoices/add.html'

    def get(self, request):
        """Открывает пустые формы реквизитов и строк накладной."""
        return render(request, self.template_name, {'form': InvoiceHeaderForm(), 'lines': InvoiceLineFormSet()})

    def post(self, request):
        """Проверяет реквизиты и строки, затем подаёт накладную."""
        form, lines = InvoiceHeaderForm(request.POST), InvoiceLineFormSet(request.POST)
        header_valid = form.is_valid()
        lines_valid = lines.is_valid()
        if header_valid and lines_valid:
            response = self.post_invoice(_header_values(form), lines.posted_lines(), form)
            if response:
                return response
        return render(request, self.template_name, {'form': form, 'lines': lines})


class InvoiceUploadView(InvoicePermissionMixin, View):
    """Обрабатывает загрузку файла, предпросмотр и подтверждение накладной."""
    permission_required = ('spares.add_receipt', 'spares.add_stockrequest')
    template_name = 'spares/invoices/upload.html'

    def get(self, request):
        """Открывает форму реквизитов и выбора XLSX-файла."""
        return render(request, self.template_name, {'form': InvoiceUploadForm()})

    def post(self, request):
        """Читает строки файла или передаёт запрос на подтверждение предпросмотра."""
        if 'confirmation' in request.POST:
            return self.confirm(request)

        form = InvoiceUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                lines = read_invoice_workbook(form.cleaned_data['workbook'])
            except ValidationError as error:
                form.add_error('workbook', error)
            else:
                return self.preview(request, _header_values(form), lines)
        return render(request, self.template_name, {'form': form})

    def preview(self, request, header, lines):
        """Показывает рассчитанные суммы и подписывает данные для подтверждения."""
        preview_lines = [
            {**line, 'amount': (line['price'] * line['quantity']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}
            for line in lines
        ]
        return render(request, 'spares/invoices/preview.html', {
            'header': header, 'lines': preview_lines, 'total': sum(line['amount'] for line in preview_lines),
            'confirmation': _prepare_preview(request.user, header, lines),
        })

    def confirm(self, request):
        """Проверяет срок подписи и автора, валидирует данные и подаёт накладную."""
        confirmation = request.POST['confirmation']
        try:
            payload = signing.loads(confirmation, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
            if payload['user'] != str(request.user.pk):
                raise signing.BadSignature
            form = InvoiceHeaderForm(payload['header'])
            lines = [InvoiceLineForm(line) for line in payload['lines']]
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            messages.error(request, 'Предпросмотр недействителен. Загрузите файл заново.')
            return redirect('invoices:upload')

        header_valid = form.is_valid()
        lines_valid = all(line.is_valid() for line in lines)
        if header_valid and lines_valid:
            response = self.post_invoice(
                _header_values(form), [line.cleaned_data for line in lines], form,
                preview_version=payload.get('version', -1),
                preview_key=sha256(confirmation.encode()).hexdigest(),
            )
            if response:
                return response
        return render(request, self.template_name, {'form': form, 'confirmation_failed': True})


class InvoiceTemplateView(InvoicePermissionMixin, View):
    """Выдаёт пустой XLSX-шаблон для подготовки строк накладной."""
    permission_required = 'spares.add_receipt'

    def get(self, request):
        """Возвращает книгу с корректным типом ответа и именем файла."""
        response = HttpResponse(
            make_invoice_workbook(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="invoice-template.xlsx"'
        return response


class InvoiceCancelView(InvoicePermissionMixin, View):
    """Запрашивает причину и разрешает отменить накладную пользователю с соответствующими правами."""
    permission_required = ('spares.view_receipt', 'spares.delete_receipt')
    template_name = 'spares/invoices/cancel.html'

    def get(self, request, pk):
        """Показывает накладную и пустую форму причины отмены."""
        invoice = get_object_or_404(ReceiptInvoice, pk=pk)
        return render(request, self.template_name, {'invoice': invoice, 'form': InvoiceCancelForm()})

    def post(self, request, pk):
        """Передаёт отмену в сервис и отображает результат либо ошибку."""
        invoice = get_object_or_404(ReceiptInvoice, pk=pk)
        form = InvoiceCancelForm(request.POST)
        if form.is_valid():
            try:
                cancel_receipt_invoice(pk=invoice.pk, actor=request.user, reason=form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Накладная отменена.')
                return redirect('invoices:detail', pk=invoice.pk)
        return render(request, self.template_name, {'invoice': invoice, 'form': form})
