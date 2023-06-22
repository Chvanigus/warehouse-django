import sys
from unittest import TestCase

from .models import WriteOff, Stock


class YourTestCase(TestCase):
    def test_something(self):
        for row in WriteOff.objects.all():
            row.save()
