from django.db.models.signals import pre_delete
from django.dispatch import receiver

from spares.models import Receipt, WriteOff, Stock


@receiver(pre_delete, sender=WriteOff)
def update_stock(sender, instance, **kwargs):
    try:
        stock = Stock.objects.get(
            spare=instance.spare,
            warehouse=instance.warehouse,
            price=instance.price,
            company=instance.company
        )
    except Stock.DoesNotExist:
        return

    if stock:
        stock.output_quantity -= instance.quantity
        stock.actual_balance += instance.quantity
        stock.save()


@receiver(pre_delete, sender=Receipt)
def delete_stock(sender, instance, **kwargs):
    stock = Stock.objects.get(
        spare=instance.spare,
        warehouse=instance.warehouse,
        price=instance.price,
        company=instance.company
    )
    if stock:
        if stock.input_quantity == instance.quantity:
            stock.delete()
        else:
            stock.input_quantity -= instance.quantity
            stock.save()
