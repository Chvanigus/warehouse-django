from django.apps import AppConfig
from django.db.models.signals import post_save, pre_delete


class SparesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'spares'
    verbose_name = 'Запчасти'

    def ready(self):
        from .signals import update_outcome_report, update_income_report, update_stock_outcome_report, delete_stock
        write_off = self.get_model('WriteOff')
        receipt = self.get_model('Receipt')

        post_save.connect(update_outcome_report, sender=write_off)
        post_save.connect(update_income_report, sender=receipt)
        pre_delete.connect(update_stock_outcome_report, sender=write_off)
        pre_delete.connect(delete_stock, sender=receipt)
