from django.urls import path

from .forms import OperationReceiptForm, OperationWriteOffForm
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
            list_title='Приход',
            related_fields=('spare', 'measure', 'company', 'warehouse', 'contractor'),
            order_by=('-date', '-pk'),
            search_fields=('spare__name', 'invoice_number', 'warehouse__name', 'contractor__name', 'company__name'),
            search_hint='Запчасть, накладная, склад или поставщик',
            add_label='Оформить приход',
            template_name='spares/operations/receipts.html',
        ),
        name='receipts',
    ),
    path(
        'writeoffs/',
        OperationListView.as_view(
            model=WriteOff,
            list_title='Расход',
            related_fields=('spare', 'measure', 'warehouse', 'company', 'worker', 'machine', 'trailer'),
            order_by=('-date', '-pk'),
            search_fields=('spare__name', 'warehouse__name', 'worker__name', 'machine__name', 'trailer__name'),
            search_hint='Запчасть, склад, работник или техника',
            add_label='Оформить списание',
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
            search_hint='Запчасть или склад',
            date_field='timestamp__date',
            template_name='spares/operations/movements.html',
            allow_add=False,
        ),
        name='movements',
    ),
]

for model, form_class, title in (
    (Receipt, OperationReceiptForm, 'Приход'),
    (WriteOff, OperationWriteOffForm, 'Расход'),
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
