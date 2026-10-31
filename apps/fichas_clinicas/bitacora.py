from apps.auditoria import servicio
from apps.auditoria.models import Operacion

from .models import AccesoFicha

_OPERACION = {
    AccesoFicha.Accion.CONSULTA: Operacion.FICHA_CONSULTA,
    AccesoFicha.Accion.CREACION: Operacion.FICHA_CREACION,
    AccesoFicha.Accion.DIAGNOSTICO: Operacion.DIAGNOSTICO_REGISTRO,
    AccesoFicha.Accion.OBSERVACION: Operacion.OBSERVACION_EXAMEN,
    AccesoFicha.Accion.RECETA: Operacion.RECETA_EMISION,
    AccesoFicha.Accion.EMERGENCIA: Operacion.EMERGENCIA_ACCESO,
}


def registrar_acceso(paciente, usuario, accion):
    """Anota el acceso en la bitácora de la ficha y en el registro de auditoría (referencia: código seudónimo)."""
    AccesoFicha.objects.create(paciente=paciente, usuario=usuario, accion=accion)
    servicio.registrar(_OPERACION[accion], 'paciente', paciente.codigo, actor=usuario)
