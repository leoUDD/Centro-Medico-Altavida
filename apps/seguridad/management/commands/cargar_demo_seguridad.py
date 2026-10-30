"""Carga usuarios y pacientes de DEMOSTRACIÓN para recorrer los controles de privacidad y RBAC.

Solo para desarrollo: las contraseñas están a la vista. No ejecutar en un entorno con datos reales.
Es idempotente: si los datos ya existen, no los duplica.
"""
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone

from apps.agenda.models import Cita
from apps.convenios.models import Cobertura, Prevision
from apps.fichas_clinicas.models import Diagnostico, HistorialMedico
from apps.pacientes.models import Paciente
from apps.profesionales.models import Profesional
from apps.sucursales.models import Sucursal
from apps.seguridad.indice import indice_rut
from apps.usuarios.forms import RegistroPacienteForm
from apps.usuarios.models import Usuario

CUENTAS = [
    # usuario, contraseña, rol, nombre, apellido
    ('sistema', 'Admin-Sistema-2026!', Usuario.Rol.ADMIN_SISTEMA, '', ''),
    ('recepcion', 'Recepcion-Altavida-2026!', Usuario.Rol.ADMINISTRATIVO, 'Paula', 'Soto'),
    ('dra.rojas', 'Medico-Rojas-2026!', Usuario.Rol.MEDICO, 'Camila', 'Rojas'),
    ('dr.navarro', 'Medico-Navarro-2026!', Usuario.Rol.MEDICO, 'Felipe', 'Navarro'),
]
CLAVE_PACIENTE = 'Paciente-Maria-2026!'


class Command(BaseCommand):
    help = 'Carga cuentas y pacientes de demostración (solo desarrollo).'

    def handle(self, *args, **opciones):
        if not settings.DEBUG:
            raise CommandError('Este comando es solo para desarrollo: defina DJANGO_DEBUG=1 en .env.')
        call_command('cargar_agenda_demo', verbosity=0)

        for username, clave, rol, nombre, apellido in CUENTAS:
            usuario, _ = Usuario.objects.get_or_create(username=username, defaults={'rol': rol})
            usuario.rol, usuario.first_name, usuario.last_name = rol, nombre, apellido
            usuario.email = f'{username}@altavida.example'
            if rol == Usuario.Rol.ADMIN_SISTEMA:
                usuario.is_staff = usuario.is_superuser = True
            usuario.set_password(clave)
            usuario.save()

        rojas = Usuario.objects.get(username='dra.rojas')
        navarro = Usuario.objects.get(username='dr.navarro')
        fonasa = Prevision.objects.filter(tipo=Prevision.Tipo.FONASA).first()

        # Paciente 1: con cuenta en el portal, atendida por la Dra. Rojas (tiene relación con ella).
        if not Paciente.objects.filter(identidad__rut_indice=indice_rut('15.482.331-K')).exists():
            form = RegistroPacienteForm({
                'nombres': 'María José', 'apellidos': 'Fuentes Soto', 'rut': '15.482.331-K',
                'fecha_nacimiento': '1985-03-12', 'email': 'maria.fuentes@correo.example', 'telefono': '+56 9 1234 4821',
                'clave': CLAVE_PACIENTE, 'clave2': CLAVE_PACIENTE, 'aviso_privacidad': 'on', 'recordatorios_correo': 'on', 'recordatorios_sms': 'on',
            })
            if not form.is_valid():
                raise CommandError(f'Registro de demo inválido: {form.errors.as_json()}')
            form.guardar()
            maria = Paciente.objects.get(identidad__rut_indice=indice_rut('15.482.331-K'))
            maria.creado_por = rojas
            maria.sexo = 'Femenino'
            maria.save()
            HistorialMedico.objects.create(paciente=maria, alergias='Penicilina', enfermedades='Diabetes tipo 2')
            Diagnostico.objects.create(
                paciente=maria, medico=rojas, codigo_cie10='E11.9', diagnostico='Diabetes mellitus tipo 2',
                tratamiento='Metformina 850 mg cada 12 horas',
            )
            if fonasa:
                Cobertura.objects.create(paciente=maria, prevision=fonasa)
            profesional = Profesional.objects.get(usuario=rojas)
            inicio = timezone.localtime().replace(hour=18, minute=0, second=0, microsecond=0)  # hoy, para verla en la agenda
            Cita.objects.create(
                paciente=maria, tipo=Cita.Tipo.CONSULTA, inicio=inicio, fin=inicio + timedelta(minutes=30),
                sucursal=Sucursal.objects.first(), profesional=profesional, modalidad=Cita.Modalidad.PRESENCIAL,
                motivo='Control de diabetes',
            )

        # Paciente 2: ficha abierta por el Dr. Navarro. La Dra. Rojas NO tiene relación (prueba del acceso de emergencia).
        if not Paciente.objects.filter(identidad__rut_indice=indice_rut('12.345.678-5')).exists():
            juan = Paciente.objects.create(
                creado_por=navarro, rut='12.345.678-5', nombres='Juan', apellidos='Pérez Mora',
                fecha_nacimiento='1972-11-02', telefono='+56 9 8765 4321', sexo='Masculino',
            )
            HistorialMedico.objects.create(paciente=juan, alergias='Ninguna conocida')
            Diagnostico.objects.create(
                paciente=juan, medico=navarro, codigo_cie10='I10', diagnostico='Hipertensión arterial',
                tratamiento='Control de presión y dieta baja en sal',
            )
            if fonasa:
                Cobertura.objects.create(paciente=juan, prevision=fonasa)

        self.stdout.write(self.style.SUCCESS('Datos de demostración cargados.'))
        self.stdout.write('\nUsuario        Contraseña                 Rol')
        for username, clave, rol, *_ in CUENTAS:
            self.stdout.write(f'{username:<14} {clave:<26} {rol.label}')
        self.stdout.write(f'{"15.482.331-K":<14} {CLAVE_PACIENTE:<26} Paciente (también entra con maria.fuentes@correo.example)')
