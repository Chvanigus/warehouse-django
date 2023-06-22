from .models import WriteOff, Stock

for row in WriteOff.objects.all():
    stock = Stock.objects.get(spare=row.spare, warehouse=row.warehouse, price=row.price, company=row.company)
    print(stock)
