from django.apps import AppConfig
from django.db.models.signals import pre_delete


class SparesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'spares'
    verbose_name = 'Запчасти'

    def ready(self):
        from .signals import update_stock, delete_stock
        write_off = self.get_model('WriteOff')
        receipt = self.get_model('Receipt')

        pre_delete.connect(update_stock, sender=write_off)
        pre_delete.connect(delete_stock, sender=receipt)
