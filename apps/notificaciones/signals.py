from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.laboratorio.models import ResultadoExamen

from .models import Notificacion


@receiver(pre_save, sender=ResultadoExamen)
def recordar_estado_anterior(sender, instance, **kwargs):
    anterior = sender.objects.filter(pk=instance.pk).values_list('estado', flat=True).first() if instance.pk else None
    instance._estado_anterior = anterior


@receiver(post_save, sender=ResultadoExamen)
def avisar_resultado_disponible(sender, instance, **kwargs):
    ahora_disponible = instance.estado == ResultadoExamen.Estado.DISPONIBLE
    if ahora_disponible and getattr(instance, '_estado_anterior', None) != ResultadoExamen.Estado.DISPONIBLE:
        # El aviso no incluye valores ni diagnósticos: solo indica que hay algo nuevo en la cuenta.
        Notificacion.objects.create(
            paciente=instance.paciente, tipo=Notificacion.Tipo.RESULTADO,
            titulo=f'Tus resultados de {instance.tipo_examen.lower()} están disponibles',
        )
