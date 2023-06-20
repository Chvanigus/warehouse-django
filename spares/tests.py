from django.test import TestCase
from .tasks import update_receipt, update_write_off

update_receipt()
update_write_off()

