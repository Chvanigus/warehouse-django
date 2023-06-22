import sys
from unittest import TestCase

from .models import WriteOff, Stock


class YourTestCase(TestCase):
    def test_something(self):
        for row in WriteOff.objects.all():
            print(row.spare, row.warehouse, row.price, row.company)
            stock = Stock.objects.filter(spare=row.spare, warehouse=row.warehouse, price=row.price, company=row.company)
            print(stock)
