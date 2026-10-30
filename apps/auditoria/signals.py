"""Eventos que nacen de cambios en las cuentas, vengan de donde vengan (administración, comandos o vistas)."""
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Operacion
from .servicio import registrar

Usuario = get_user_model()


@receiver(pre_save, sender=Usuario)
def recordar_estado_anterior(sender, instance, **kwargs):
    anterior = sender.objects.filter(pk=instance.pk).values('rol', 'is_active').first() if instance.pk else None
    instance._auditoria_anterior = anterior


@receiver(post_save, sender=Usuario)
def auditar_cuenta(sender, instance, created, **kwargs):
    # Las cuentas de pacientes se crean en el registro público: se auditan igual, con su id interno (sin nombre ni correo).
    if created:
        registrar(Operacion.CUENTA_CREADA, 'cuenta', instance.pk, detalle={'tipo': instance.rol})
        return
    anterior = getattr(instance, '_auditoria_anterior', None) or {}
    if anterior.get('rol') and anterior['rol'] != instance.rol:
        registrar(Operacion.CUENTA_ROL_CAMBIO, 'cuenta', instance.pk,
                  detalle={'rol_anterior': anterior['rol'], 'rol_nuevo': instance.rol})
    if 'is_active' in anterior and anterior['is_active'] != instance.is_active:
        registrar(Operacion.CUENTA_ESTADO_CAMBIO, 'cuenta', instance.pk,
                  detalle={'estado_anterior': 'activa' if anterior['is_active'] else 'inactiva',
                           'estado_nuevo': 'activa' if instance.is_active else 'inactiva'})
