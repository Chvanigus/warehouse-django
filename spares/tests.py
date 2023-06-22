from .models import WriteOff

for row in WriteOff.objects.all():
    row.save()
