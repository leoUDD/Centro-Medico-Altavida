from datetime import time

from django.core.management.base import BaseCommand

from apps.agenda.models import HorarioAtencion, HorarioLaboratorio
from apps.laboratorio.models import TipoExamen
from apps.profesionales.models import Especialidad, Profesional
from apps.sucursales.models import Sucursal
from apps.usuarios.models import Usuario

ESPECIALIDADES = ['Medicina general', 'Medicina interna', 'Pediatría', 'Ginecología', 'Traumatología']
EXAMENES = [
    ('Perfil lipídico', '8 a 12', 'Requiere ayuno de 8 a 12 horas. Puedes tomar agua.'),
    ('Hemograma completo', '', ''),
    ('Glicemia en ayunas', '8 a 12', 'Requiere ayuno de 8 a 12 horas. Puedes tomar agua.'),
    ('Hemoglobina glicosilada', '', ''),
    ('Orina completa', '', 'Usa el frasco estéril que te entregamos en el laboratorio.'),
]
MEDICOS = [('dra.rojas', 'Camila', 'Rojas', 'Dra.', 'Medicina general'), ('dr.navarro', 'Felipe', 'Navarro', 'Dr.', 'Medicina general')]


class Command(BaseCommand):
    help = 'Carga sedes, especialidades, médicos, horarios y exámenes de ejemplo para probar el agendamiento (idempotente).'

    def handle(self, *args, **opciones):
        central, _ = Sucursal.objects.get_or_create(nombre='Sede Central', defaults={'direccion': 'Av. Principal 123'})
        oriente, _ = Sucursal.objects.get_or_create(nombre='Sede Oriente', defaults={'direccion': 'Calle Oriente 456'})
        for nombre in ESPECIALIDADES:
            Especialidad.objects.get_or_create(nombre=nombre)
        for nombre, ayuno, preparacion in EXAMENES:
            TipoExamen.objects.get_or_create(nombre=nombre, defaults={'ayuno_horas': ayuno, 'preparacion': preparacion})

        general = Especialidad.objects.get(nombre='Medicina general')
        for username, nombre, apellido, titulo, _esp in MEDICOS:
            usuario, creado = Usuario.objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@altavida.example', 'first_name': nombre, 'last_name': apellido, 'rol': Usuario.Rol.MEDICO},
            )
            if creado:
                usuario.set_unusable_password()  # entra solo cuando la administración le asigne una contraseña
                usuario.save()
            profesional, _ = Profesional.objects.get_or_create(usuario=usuario, defaults={'especialidad': general, 'titulo': titulo})
            if not profesional.horarios.exists():
                for dia in range(5):
                    HorarioAtencion.objects.create(profesional=profesional, sucursal=central, dia_semana=dia, hora_inicio=time(8, 30), hora_fin=time(12, 0))
                    HorarioAtencion.objects.create(profesional=profesional, sucursal=central, dia_semana=dia, hora_inicio=time(15, 0), hora_fin=time(17, 0))

        for sede in (central, oriente):
            if not sede.horarios_laboratorio.exists():
                for dia in range(6):
                    HorarioLaboratorio.objects.create(sucursal=sede, dia_semana=dia, hora_inicio=time(7, 30), hora_fin=time(12, 0), duracion_minutos=15, cupos=2)
        self.stdout.write(self.style.SUCCESS('Datos de agenda cargados.'))
