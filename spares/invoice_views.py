from decimal import Decimal, ROUND_HALF_UP
from re import escape

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count, Prefetch, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import JournalFilterForm
from .invoice_forms import InvoiceCancelForm, InvoiceHeaderForm, InvoiceLineForm, InvoiceLineFormSet, InvoiceUploadForm
from .invoice_models import ReceiptInvoice
from .invoice_services import cancel_receipt_invoice, invoice_version, post_receipt_invoice
from .invoice_xlsx import make_invoice_workbook, read_invoice_workbook
from .models import Receipt


HEADER_FIELDS = tuple(InvoiceHeaderForm.base_fields)
PREVIEW_SALT = 'warehouse.receipt-invoice.v1'
PREVIEW_MAX_AGE = 20 * 60


def _prepare_preview(actor, header, lines):
    return signing.dumps({
        'user': str(actor.pk),
        'version': invoice_version(header, ReceiptInvoice.normalize_number(header['number'])),
        'header': {
            'number': header['number'], 'date': header['date'].isoformat(),
            'company': header['company'].pk, 'contractor': header['contractor'].pk,
            'warehouse': header['warehouse'].pk,
        },
        'lines': [{
            'spare': line['spare'].pk, 'measure': line['measure'].pk if line['measure'] else '',
            'quantity': str(line['quantity']), 'price': str(line['price']),
        } for line in lines],
    }, salt=PREVIEW_SALT, compress=True)


def _header_values(form):
    return {name: form.cleaned_data[name] for name in HEADER_FIELDS}


class InvoicePermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    def redirect_after_posting(self, invoice):
        if self.request.user.has_perm('spares.view_receipt'):
            return redirect('invoices:detail', pk=invoice.pk)
        return redirect('spares:warehouse_main')

    def post_invoice(self, header, lines, error_form, *, preview_version=None):
        try:
            invoice = post_receipt_invoice(
                actor=self.request.user, header=header, lines=lines, preview_version=preview_version,
            )
        except ValidationError as error:
            error_form.add_error(None, error)
        except IntegrityError:
            error_form.add_error(None, 'Накладная не проведена. Проверьте номер и справочники и повторите попытку.')
        else:
            messages.success(self.request, 'Накладная проведена.')
            return self.redirect_after_posting(invoice)
        return None


class InvoiceListView(InvoicePermissionMixin, ListView):
    permission_required = 'spares.view_receipt'
    template_name = 'spares/invoices/list.html'
    context_object_name = 'invoices'
    paginate_by = 30
    queryset = ReceiptInvoice.objects.select_related('company', 'contractor', 'warehouse').annotate(
        line_count=Count('lines'), total=Sum('lines__amount'),
    ).order_by('-date', '-pk')

    @cached_property
    def filters(self):
        form = JournalFilterForm(self.request.GET or None)
        form.fields['q'].widget.attrs['placeholder'] = 'Номер или поставщик'
        return form

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.filters.is_bound:
            return queryset
        if not self.filters.is_valid():
            return queryset.none()
        data = self.filters.cleaned_data
        if data['q']:
            pattern = escape(data['q'])
            queryset = queryset.filter(Q(number__iregex=pattern) | Q(contractor__name__iregex=pattern))
        if data['date_from']:
            queryset = queryset.filter(date__gte=data['date_from'])
        if data['date_to']:
            queryset = queryset.filter(date__lte=data['date_to'])
        return queryset

    def get_context_data(self, **kwargs):
        return super().get_context_data(filters=self.filters, **kwargs)


class InvoiceDetailView(InvoicePermissionMixin, DetailView):
    permission_required = 'spares.view_receipt'
    template_name = 'spares/invoices/detail.html'
    context_object_name = 'invoice'
    queryset = ReceiptInvoice.objects.select_related('company', 'contractor', 'warehouse').prefetch_related(
        Prefetch('lines', queryset=Receipt.objects.select_related('spare', 'measure').order_by('pk')),
    ).annotate(total=Sum('lines__amount'))


class InvoiceAddView(InvoicePermissionMixin, View):
    permission_required = 'spares.add_receipt'
    template_name = 'spares/invoices/add.html'

    def get(self, request):
        return render(request, self.template_name, {'form': InvoiceHeaderForm(), 'lines': InvoiceLineFormSet()})

    def post(self, request):
        form, lines = InvoiceHeaderForm(request.POST), InvoiceLineFormSet(request.POST)
        header_valid = form.is_valid()
        lines_valid = lines.is_valid()
        if header_valid and lines_valid:
            response = self.post_invoice(_header_values(form), lines.posted_lines(), form)
            if response:
                return response
        return render(request, self.template_name, {'form': form, 'lines': lines})


class InvoiceUploadView(InvoicePermissionMixin, View):
    permission_required = 'spares.add_receipt'
    template_name = 'spares/invoices/upload.html'

    def get(self, request):
        return render(request, self.template_name, {'form': InvoiceUploadForm()})

    def post(self, request):
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
        preview_lines = [
            {**line, 'amount': (line['price'] * line['quantity']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}
            for line in lines
        ]
        return render(request, 'spares/invoices/preview.html', {
            'header': header, 'lines': preview_lines, 'total': sum(line['amount'] for line in preview_lines),
            'confirmation': _prepare_preview(request.user, header, lines),
        })

    def confirm(self, request):
        try:
            payload = signing.loads(request.POST['confirmation'], salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
            if payload['user'] != str(request.user.pk):
                raise signing.BadSignature
        except (signing.BadSignature, ValueError, KeyError):
            messages.error(request, 'Предпросмотр недействителен. Загрузите файл заново.')
            return redirect('invoices:upload')

        form = InvoiceHeaderForm(payload['header'])
        lines = [InvoiceLineForm(line) for line in payload['lines']]
        header_valid = form.is_valid()
        lines_valid = all(line.is_valid() for line in lines)
        if header_valid and lines_valid:
            response = self.post_invoice(
                _header_values(form), [line.cleaned_data for line in lines], form,
                preview_version=payload.get('version', -1),
            )
            if response:
                return response
        return render(request, self.template_name, {'form': form, 'confirmation_failed': True})


class InvoiceTemplateView(InvoicePermissionMixin, View):
    permission_required = 'spares.add_receipt'

    def get(self, request):
        response = HttpResponse(
            make_invoice_workbook(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="invoice-template.xlsx"'
        return response


class InvoiceCancelView(InvoicePermissionMixin, View):
    permission_required = ('spares.view_receipt', 'spares.delete_receipt')
    template_name = 'spares/invoices/cancel.html'

    def get(self, request, pk):
        invoice = get_object_or_404(ReceiptInvoice, pk=pk)
        return render(request, self.template_name, {'invoice': invoice, 'form': InvoiceCancelForm()})

    def post(self, request, pk):
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
