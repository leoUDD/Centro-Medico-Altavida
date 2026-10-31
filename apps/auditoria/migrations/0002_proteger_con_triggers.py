"""Protege el registro de auditoría dentro de la propia base de datos.

Aunque alguien eluda la aplicación y escriba SQL directo, la base rechaza:
- modificar (UPDATE) cualquier evento o punto de control;
- eliminar (DELETE) un punto de control;
- eliminar un evento con menos de 24 meses (el plazo mínimo de conservación).
Solo `manage.py purgar_auditoria` elimina eventos, y únicamente los vencidos.

SQLite se prueba con la suite del proyecto. La variante PostgreSQL es el equivalente para producción: no se ejecuta
en las pruebas y debe verificarse al desplegar.
"""
from django.db import migrations

MESES_MINIMOS = 24

SQLITE = [
    """CREATE TRIGGER auditoria_evento_sin_update BEFORE UPDATE ON auditoria_eventoauditoria
       BEGIN SELECT RAISE(ABORT, 'Los eventos de auditoría no se pueden modificar'); END;""",
    f"""CREATE TRIGGER auditoria_evento_sin_delete BEFORE DELETE ON auditoria_eventoauditoria
       WHEN OLD.fecha > strftime('%Y-%m-%d %H:%M:%f', 'now', '-{MESES_MINIMOS} months')
       BEGIN SELECT RAISE(ABORT, 'Los eventos de auditoría no se pueden eliminar antes de {MESES_MINIMOS} meses'); END;""",
    """CREATE TRIGGER auditoria_punto_sin_update BEFORE UPDATE ON auditoria_puntocontrolauditoria
       BEGIN SELECT RAISE(ABORT, 'Los puntos de control no se pueden modificar'); END;""",
    """CREATE TRIGGER auditoria_punto_sin_delete BEFORE DELETE ON auditoria_puntocontrolauditoria
       BEGIN SELECT RAISE(ABORT, 'Los puntos de control no se pueden eliminar'); END;""",
]
SQLITE_REVERSA = [
    'DROP TRIGGER IF EXISTS auditoria_evento_sin_update', 'DROP TRIGGER IF EXISTS auditoria_evento_sin_delete',
    'DROP TRIGGER IF EXISTS auditoria_punto_sin_update', 'DROP TRIGGER IF EXISTS auditoria_punto_sin_delete',
]

POSTGRES = [
    f"""CREATE OR REPLACE FUNCTION auditoria_proteger() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'El registro de auditoría no se puede modificar'; END IF;
      IF TG_TABLE_NAME = 'auditoria_puntocontrolauditoria' THEN RAISE EXCEPTION 'Los puntos de control no se pueden eliminar'; END IF;
      IF OLD.fecha > now() - interval '{MESES_MINIMOS} months' THEN
        RAISE EXCEPTION 'Los eventos de auditoría no se pueden eliminar antes de {MESES_MINIMOS} meses';
      END IF;
      RETURN OLD;
    END; $$ LANGUAGE plpgsql;""",
    """CREATE TRIGGER auditoria_evento_proteger BEFORE UPDATE OR DELETE ON auditoria_eventoauditoria
       FOR EACH ROW EXECUTE FUNCTION auditoria_proteger();""",
    """CREATE TRIGGER auditoria_punto_proteger BEFORE UPDATE OR DELETE ON auditoria_puntocontrolauditoria
       FOR EACH ROW EXECUTE FUNCTION auditoria_proteger();""",
]
POSTGRES_REVERSA = [
    'DROP TRIGGER IF EXISTS auditoria_evento_proteger ON auditoria_eventoauditoria',
    'DROP TRIGGER IF EXISTS auditoria_punto_proteger ON auditoria_puntocontrolauditoria',
    'DROP FUNCTION IF EXISTS auditoria_proteger()',
]


def _ejecutar(editor, sentencias):
    for sentencia in sentencias:
        editor.execute(sentencia)


def crear(apps, editor):
    if editor.connection.vendor == 'sqlite':
        _ejecutar(editor, SQLITE)
    elif editor.connection.vendor == 'postgresql':
        _ejecutar(editor, POSTGRES)
    else:
        raise NotImplementedError(
            f'El registro de auditoría exige triggers de protección y no hay variante para {editor.connection.vendor}.'
        )


def quitar(apps, editor):
    if editor.connection.vendor == 'sqlite':
        _ejecutar(editor, SQLITE_REVERSA)
    elif editor.connection.vendor == 'postgresql':
        _ejecutar(editor, POSTGRES_REVERSA)


class Migration(migrations.Migration):

    dependencies = [
        ('auditoria', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear, quitar),
    ]
