from django.db.models import Sum
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from spares.models import Receipt, WriteOff, Stock
from spares.utils import get_month_name
from reports.models import IncomeReport, OutcomeReport


@receiver(post_save, sender=WriteOff)
def update_outcome_report(sender, instance, created, **kwargs):
    if created or instance.date.year != instance.year:
        report, _ = OutcomeReport.objects.get_or_create(company=instance.company)

        expenses = WriteOff.objects.filter(company=instance.company, year=instance.date.year) \
            .aggregate(total_price=Sum('total_amount'))['total_price']

        if expenses is not None:
            setattr(report, instance.date.strftime('%B').lower(), expenses)
            report.save()


@receiver(post_save, sender=Receipt)
def update_income_report(sender, instance, created, **kwargs):
    if created or instance.date.year != instance.year:
        report, _ = IncomeReport.objects.get_or_create(company=instance.company)

        expenses = Receipt.objects.filter(company=instance.company, year=instance.date.year) \
            .aggregate(total_price=Sum('amount'))['total_price']

        if expenses is not None:
            setattr(report, instance.date.strftime('%B').lower(), expenses)
            report.save()


@receiver(pre_delete, sender=WriteOff)
def update_stock_outcome_report(sender, instance, **kwargs):
    stock = Stock.objects.get(
        spare=instance.spare,
        warehouse=instance.warehouse,
        price=instance.price,
        company=instance.company
    )
    if stock:
        stock.output_quantity -= instance.quantity
        stock.save()

    try:
        output = OutcomeReport.objects.get(company=instance.company, year=instance.date.year)
    except OutcomeReport.DoesNotExist:
        output = None

    if output:
        month_name = get_month_name(instance.date)
        setattr(output, month_name, getattr(output, month_name) - instance.total_amount)
        output.save()


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

    try:
        input_ = IncomeReport.objects.get(company=instance.company, year=instance.date.year)
    except IncomeReport.DoesNotExist:
        input_ = None

    if input_:
        month_name = get_month_name(instance.date)
        setattr(input_, month_name, getattr(input_, month_name) - instance.amount)
        input_.save()
