from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Assinatura, Barbearia


@receiver(post_save, sender=Barbearia)
def criar_assinatura_de_teste(sender, instance, created, **kwargs):
    if created:
        Assinatura.objects.get_or_create(barbearia=instance)
