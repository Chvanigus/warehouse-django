import logging

from django.db.models import Sum

from .models import Receipt, Stock, WriteOff

logger = logging.getLogger(__name__)


def update_receipt():
    """Обновляет данные по таблице Receipt."""
    logger.critical('Запущена задача проверки остатков по приходу')

    spare_parts = Receipt.objects.values('spare', 'price', 'warehouse', 'measure', 'company').distinct()
    if spare_parts:
        for spare_part in spare_parts:
            total_quantity = Receipt.objects.filter(
                spare=spare_part['spare'],
                price=spare_part['price'],
                warehouse=spare_part['warehouse']
            ).aggregate(total_quantity=Sum('quantity'))['total_quantity']

            Stock.objects.update_or_create(
                spare_id=spare_part['spare'],
                price=spare_part['price'],
                warehouse_id=spare_part['warehouse'],
                input_quantity=total_quantity,
                measure_id=spare_part['measure'],
                company=spare_part['company']
            )


def update_write_off():
    """Обновляет данные по таблице Receipt."""
    logger.critical('Запущена задача проверки остатков по списанию')

    write_off_parts = WriteOff.objects.values('spare', 'price', 'warehouse', 'company').distinct()
    if write_off_parts:
        for spare_part in write_off_parts:
            output_quantity = WriteOff.objects.filter(
                spare=spare_part['spare'],
                price=spare_part['price'],
                warehouse=spare_part['warehouse']
            ).aggregate(output_quantity=Sum('quantity'))['output_quantity']

            Stock.objects.update(
                spare_id=spare_part['spare'],
                price=spare_part['price'],
                warehouse_id=spare_part['warehouse'],
                output_quantity=output_quantity,
                company=spare_part['company']
            )
