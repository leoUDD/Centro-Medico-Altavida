from .models import AccesoFicha


def registrar_acceso(paciente, usuario, accion):
    AccesoFicha.objects.create(paciente=paciente, usuario=usuario, accion=accion)
