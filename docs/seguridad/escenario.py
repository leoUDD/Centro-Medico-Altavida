"""Corre un escenario completo en una base de prueba temporal y vuelca los eventos de auditoría reales."""
import json
import re
import sys

from django.core import mail
from django.db import connection
from django.test.utils import setup_test_environment

setup_test_environment()
connection.creation.create_test_db(verbosity=0, autoclobber=True)
mail.outbox = []

from django.test import Client
from django.urls import reverse

from apps.auditoria import alertas, contencion, incidentes, servicio
from apps.auditoria.models import AlertaSeguridad, EventoAuditoria
from apps.consentimientos import servicio as cons
from apps.derechos import servicio as der
from apps.fichas_clinicas.models import Diagnostico
from apps.pacientes.models import Paciente
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'
U = Usuario.objects
medico = U.create_user('dra.rojas', email='r@c.cl', password=CLAVE, rol='MEDICO')
priv = U.create_user('encargada', email='p@c.cl', password=CLAVE, rol='PRIVACIDAD')
sysadm = U.create_user('sistemas', email='s@c.cl', password=CLAVE, rol='ADMIN_SISTEMA')
u_ana = U.create_user('ana', email='a@c.cl', password=CLAVE, rol='PACIENTE')
ana = Paciente.objects.create(usuario=u_ana, rut='111111111', nombres='Ana', apellidos='Prueba',
                              fecha_nacimiento='1985-03-12', email='ana@correo.cl', telefono='+56 9 1234 4821')
Diagnostico.objects.create(paciente=ana, medico=medico, diagnostico='Gastritis')
ana.refresh_from_db()

# 1) Consentimiento: otorgar y revocar
cons.otorgar(ana, cons.RECORDATORIOS_CORREO, u_ana)
cons.revocar(ana, cons.RECORDATORIOS_CORREO, u_ana)

# 2) Derechos: acceso con verificación fallida y luego exitosa, resolución, descarga y cierre
s = der.crear(ana, ana, 'ACCESO', u_ana)
codigo = re.search(r'es (\d{6})\.', mail.outbox[-1].body).group(1)
try:
    der.verificar(s, u_ana, False, codigo)
except der.DerechosError:
    pass
der.verificar(s, u_ana, True, codigo)
der.resolver(s, priv, 'EJECUTADA', '', 'Tu copia está disponible.')
der.registrar_descarga(s, u_ana)
der.cerrar(s, priv)

# 3) Rectificación de teléfono
r = der.crear(ana, ana, 'RECTIFICACION', u_ana, campo='telefono', valor='+56 9 5555 0000')
der.verificar(r, u_ana, True)
der.resolver(r, priv, 'EJECUTADA')

# 4) Intento de leer la auditoría sin permiso y lectura autorizada
from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')
c = Client()
c.force_login(medico)
c.get(reverse('auditoria:eventos'))
c.force_login(priv)
c.get(reverse('auditoria:eventos'), HTTP_HOST='localhost')

# 5) Alerta y contención: ráfaga de consultas de un médico
for n in range(60):
    servicio.registrar('FICHA_CONSULTA', 'paciente', f'Pdemo{n:03d}', actor=medico)
nuevas = alertas.detectar()
contencion.revocar_sesiones(medico, priv)

# 6) Incidente
inc = incidentes.abrir('Consultas masivas de fichas desde una cuenta médica', 'ALTA', priv, nuevas[:1])
incidentes.clasificar(inc, 'CONFIRMADO', priv, afecta_datos_personales=True, riesgo_razonable=True, hay_datos_sensibles=True, titulares_aprox=60)
incidentes.avanzar(inc, priv, 'a' * 64)
incidentes.proponer_notificacion(inc, priv)
incidentes.autorizar_notificacion(inc, sysadm)
incidentes.registrar_notificacion(inc, priv, 'csirt_alerta')

salida = []
total = EventoAuditoria.objects.count()
for e in EventoAuditoria.objects.exclude(operacion='FICHA_CONSULTA').order_by('id'):
    salida.append(f"#{e.id} | {e.fecha:%Y-%m-%d %H:%M:%S}Z | {e.actor_rol or '-'} | {e.operacion} | {e.recurso_tipo}:{e.recurso_ref[:14]} | {e.resultado} | {json.dumps(e.detalle, ensure_ascii=False)} | hash {e.hash[:12]}…")
salida.append('')
salida.append(f'Eventos FICHA_CONSULTA omitidos en este listado: {EventoAuditoria.objects.filter(operacion="FICHA_CONSULTA").count()} (total en la base: {total})')
salida.append(f'verificar() -> {servicio.verificar()}')
salida.append(f'Alertas generadas: {[(a.regla, a.severidad) for a in AlertaSeguridad.objects.all()]}')
salida.append(f'Plazos del caso {inc.codigo}: ' + '; '.join(f'{k}: límite {v[1]:%d-%m %H:%M}' for k, v in inc.plazos.items()))
open(sys.argv[-1] if sys.argv[-1].endswith('.txt') else r'C:/Users/Soporte/AppData/Local/Temp/claude/C--Users-Soporte-Proyectos-Centro-Medico-Altavida/b570f3c3-69f3-40e6-8836-1741de770596/scratchpad/eventos_ejemplo.txt', 'w', encoding='utf-8').write('\n'.join(salida))
connection.creation.destroy_test_db(':memory:', verbosity=0) if False else None
print('\n'.join(salida))
