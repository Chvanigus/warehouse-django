from django.urls import path

from .forms import ReceiptForm, WriteOffForm
from .models import Movement, Receipt, WriteOff
from .operation_views import (
    OperationCreateView,
    OperationDeleteView,
    OperationListView,
    OperationUpdateView,
)

app_name = 'operations'

urlpatterns = [
    path(
        'receipts/',
        OperationListView.as_view(
            model=Receipt,
            list_title='Приходы',
            related_fields=('spare', 'measure', 'company', 'warehouse', 'contractor'),
            order_by=('-date', '-pk'),
            search_fields=('spare__name', 'invoice_number', 'warehouse__name', 'contractor__name'),
            template_name='spares/operations/receipts.html',
        ),
        name='receipts',
    ),
    path(
        'writeoffs/',
        OperationListView.as_view(
            model=WriteOff,
            list_title='Списания',
            related_fields=('spare', 'measure', 'warehouse', 'company', 'worker', 'machine', 'trailer'),
            order_by=('-date', '-pk'),
            search_fields=('spare__name', 'warehouse__name', 'worker__name', 'machine__name', 'trailer__name'),
            template_name='spares/operations/writeoffs.html',
        ),
        name='writeoffs',
    ),
    path(
        'movements/',
        OperationListView.as_view(
            model=Movement,
            list_title='Перемещения',
            related_fields=('spare', 'from_warehouse', 'to_warehouse'),
            order_by=('-timestamp', '-pk'),
            search_fields=('spare__name', 'from_warehouse__name', 'to_warehouse__name'),
            template_name='spares/operations/movements.html',
            allow_add=False,
        ),
        name='movements',
    ),
]

for model, form_class, title in (
    (Receipt, ReceiptForm, 'Приходы'),
    (WriteOff, WriteOffForm, 'Списания'),
):
    name = model._meta.model_name
    prefix = f'{name}s/'
    urlpatterns += [
        path(
            f'{prefix}add/',
            OperationCreateView.as_view(model=model, form_class=form_class, list_title=title),
            name=f'{name}_add',
        ),
        path(
            f'{prefix}<int:pk>/edit/',
            OperationUpdateView.as_view(model=model, form_class=form_class, list_title=title),
            name=f'{name}_edit',
        ),
        path(
            f'{prefix}<int:pk>/delete/',
            OperationDeleteView.as_view(model=model, list_title=title),
            name=f'{name}_delete',
        ),
    ]
