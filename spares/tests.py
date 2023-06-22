from .models import Receipt, WriteOff

for row in Receipt.objects.all():
    row.save()

for row in WriteOff.objects.all():
    row.save()
