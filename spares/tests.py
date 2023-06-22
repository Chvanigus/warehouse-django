from .models import WriteOff

for row in WriteOff.objects.all():
    print(row)
    row.save()
