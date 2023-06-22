import sys
from unittest import TestCase

from .models import WriteOff, Receipt


class YourTestCase(TestCase):
    def test_something(self):
        for row in Receipt.objects.all():
            row.save()

        for row in WriteOff.objects.all():
            row.save()
