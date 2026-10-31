# Diseño del módulo de gestión del consentimiento

Centro Médico Altavida · IIT421W Seguridad y Protección de Datos · Actividad 4 (Hito 3)

## 1. Qué consentimiento se gestiona y cuál no

El análisis de bases de licitud del Hito 1 concluyó que la atención clínica (ficha, diagnósticos, recetas, resultados, agendamiento) **no se funda en el consentimiento**: se funda en la obligación legal de llevar la ficha (Ley 20.584 y DS 41/2012 de Salud), en la ejecución del contrato de atención y en la excepción para el tratamiento de datos de salud con fines asistenciales. Pedir un "autorizo el tratamiento de mis datos" para eso sería engañoso, porque el paciente no podría rechazarlo sin perder la atención, y el consentimiento libre exige poder negarse sin consecuencias.

Por eso el módulo gestiona solo los usos que el paciente **puede rechazar sin perder su atención**. Hoy son dos finalidades, una por canal:

| Código | Finalidad | Dato que usa | Fundamento |
| --- | --- | --- | --- |
| `RECORDATORIOS_CORREO` | Avisar por correo de las próximas citas | Correo, nombre de pila, fecha, hora y profesional | Consentimiento (Ley 21.719, art. 12) |
| `RECORDATORIOS_SMS` | Avisar por SMS de las próximas citas | Teléfono, nombre de pila, fecha, hora y profesional | Consentimiento (Ley 21.719, art. 12) |

Ningún recordatorio incluye diagnósticos ni datos clínicos. Agregar una finalidad nueva es cargar una fila en `Finalidad` y su primer texto; no requiere cambiar el modelo.

**Cambio frente a la versión anterior.** El registro tenía una casilla única "autorizo el tratamiento de mis datos personales y de salud" y un booleano `recordatorios_activos` que activaba correo y SMS a la vez. Se reemplazaron por: (a) un acuse de lectura del aviso de privacidad, que no es consentimiento, y (b) consentimientos opcionales, sin marcar de antemano, uno por canal.

## 2. Modelo de datos

| Tabla | Para qué sirve | Campos principales |
| --- | --- | --- |
| `Finalidad` | Catálogo de finalidades consentibles | código, nombre, descripción, dato usado, base de licitud, canal, versión mínima válida, activa |
| `TextoConsentimiento` | Texto exacto mostrado, con versión. Inalterable | finalidad, versión, texto, huella SHA-256, fecha de publicación, cambia alcance |
| `Consentimiento` | Estado actual por paciente y finalidad (único por par) | paciente, finalidad, texto aceptado, estado (otorgado/revocado), fecha de otorgamiento, fecha de revocación, otorgante, representación |
| `RegistroConsentimiento` | Historial: una fila por cada otorgamiento o revocación. Inalterable | paciente, finalidad, texto, acción, fecha y hora, otorgante, representación, canal, cuenta que registró |
| `Representacion` | Vínculo verificado entre un menor y su representante legal | menor, representante, parentesco, estado, documento revisado, quién y cuándo verificó, vigente hasta |
| `Paciente.aviso_privacidad_version/_en` | Acuse de lectura del aviso (no es consentimiento) | versión y fecha |

Lo que se exige de un consentimiento, y dónde queda:

- **Fecha y hora:** `otorgado_en` / `revocado_en` y `RegistroConsentimiento.fecha`.
- **Finalidad:** `Finalidad.codigo`, una por fila.
- **Versión del texto:** `TextoConsentimiento.version` y su huella SHA-256. El consentimiento apunta al texto exacto que se aceptó; si el texto cambia, se publica otra versión y la anterior se conserva.
- **Estado:** `Consentimiento.estado`, con el historial completo en `RegistroConsentimiento`.

Inalterabilidad: `TextoConsentimiento` y `RegistroConsentimiento` lanzan error si se intenta modificar o borrar una fila desde la aplicación. Esto protege contra errores y usos indebidos del código, **no** contra alguien con acceso directo a la base de datos; para eso la auditoría registra cada cambio en una cadena con hash (documento 03).

## 3. Reglas de negocio

- **Un consentimiento no habilita otro.** El estado se guarda por (paciente, finalidad) con una restricción de unicidad, y los procesos consultan una sola función, `vigente(paciente, código)`. Dar el permiso del correo no activa el SMS, y ningún permiso de recordatorios habilita otro uso futuro (marketing, investigación): serían otras finalidades, con su propio texto y su propia decisión. Esto responde al principio de finalidad: cada permiso cubre únicamente el propósito que se explicó.
- **Revocar es tan fácil como otorgar.** Un clic en "Mis consentimientos". Revocar deja fecha y hora, no pide justificación y no afecta la atención.
- **Reconfirmación.** Si cambia el alcance de un texto, se publica una versión nueva y se sube `version_minima_valida`: los consentimientos dados con textos anteriores dejan de valer hasta que el paciente los confirme otra vez, y la pantalla lo muestra como "Hay que reconfirmar".
- **No se ensucia el historial.** Repetir una acción que no cambia nada (otorgar lo ya otorgado, revocar lo no otorgado) no genera filas.
- **Pacientes con datos bloqueados** por una supresión no pueden dar consentimientos nuevos.

## 4. Cómo se refleja la revocación en los procesos

La revocación se aplica en tres puntos, porque revisar solo uno dejaría una ventana:

1. **Al generar recordatorios** (`recordatorios.generar`): un canal solo sale si la regla lo usa, el paciente lo prefiere **y** hay consentimiento vigente para ese canal.
2. **Al enviar** (`recordatorios.enviar_pendientes`): se revisa de nuevo. Si el paciente revocó después de que el recordatorio se generó, este pasa a estado `CANCELADO` ("Sin consentimiento vigente") y no se envía. Es la parte más importante: sin ella, un aviso ya programado seguiría saliendo.
3. **En las preferencias del portal:** no se puede activar un canal sin consentimiento; el servidor lo rechaza con un mensaje, aunque alguien fabrique la petición a mano. Las preferencias iniciales de un paciente nuevo parten de los canales que consintió.

Lo que la revocación **no** cambia: citas, ficha, recetas y resultados, porque no dependen de este consentimiento. El aviso de la propia cuenta del portal (notificación interna) tampoco, porque no usa correo ni teléfono.

## 5. Trazabilidad sin datos innecesarios

El historial responde "quién decidió qué, sobre qué texto y cuándo" y nada más. **No se guardan**: direcciones IP, agente de navegador, copia del correo o del teléfono, ni el texto en claro dentro de la auditoría (solo el código de finalidad, la versión y el estado). El paciente aparece por su código seudónimo. Los eventos de auditoría de consentimiento llevan finalidad, estado anterior, estado nuevo, versión y canal de origen (portal, migración de datos anteriores o supresión por derechos). La pantalla del Encargado de privacidad muestra cifras y movimientos con códigos seudónimos, nunca nombres.

## 6. Menores de edad: flujo con representante legal

Aplica porque el centro atiende menores. Regla adoptada: **hasta los 18 años el consentimiento lo da el representante legal.**

1. El registro público rechaza a menores: un menor no crea cuenta propia. Su ficha puede existir sin cuenta (la abre el médico) y quien actúa en su nombre es su representante, desde su propia cuenta.
2. En recepción, el representante acredita en persona el vínculo (certificado de nacimiento, resolución judicial u otro documento legal). El personal registra **qué documento revisó**, quién verificó y cuándo; no se escanea ni se guarda copia. Ambas personas deben existir como pacientes.
3. La representación nace `VERIFICADA` con una fecha `vigente_hasta` (el día que el menor cumple 18). Recepción puede terminarla antes.
4. El representante ve a su representado en "Mis consentimientos" y decide por él. Cada registro guarda `otorgante = REPRESENTANTE` y la representación usada.
5. Un menor no puede consentir por sí mismo, y un tercero sin representación vigente es rechazado y deja un evento `DENEGADO` en la auditoría.
6. **El consentimiento depende de la representación:** si esta termina o vence, `vigente()` pasa a falso de inmediato y `cerrar_vencidos` registra la revocación.

Limitación declarada: la Ley 21.719 distingue a los menores de 14 años de los adolescentes de 14 a 17 (para estos últimos pueden aplicar reglas distintas según el tipo de dato). Se adoptó el criterio más conservador, 18, hasta confirmar con asesoría jurídica; está en una constante (`EDAD_CONSENTIMIENTO_PROPIO`) para ajustarlo en un solo lugar.

## 7. Pantallas

- **Aviso de privacidad** (público): finalidades, fundamentos, conservación, derechos y menores.
- **Registro:** acuse del aviso (obligatorio, solo informa) y dos casillas opcionales por canal.
- **Mis consentimientos** (paciente): estado de cada finalidad, texto exacto con su versión, fechas, botones autorizar y retirar, historial; y las autorizaciones de sus representados.
- **Representantes legales** (recepción): registrar y terminar representaciones.
- **Consentimientos** (Encargado de privacidad): totales por finalidad y últimos movimientos con códigos seudónimos.

## 8. Migración de los datos anteriores

La migración `consentimientos.0002` crea las dos finalidades con su texto v1 y convierte lo que había: quien marcó la casilla general queda con acuse del aviso v1 en la misma fecha; quien tenía `recordatorios_activos` queda con un consentimiento por cada canal y un registro de origen `MIGRACION`. Después la migración de `pacientes` elimina los tres campos antiguos. En la base de desarrollo convirtió 2 finalidades, 4 consentimientos y 4 registros.

Advertencia honesta: esos consentimientos migrados se dieron con la casilla antigua, cuyo texto no distinguía canales ni explicaba qué dato se usaba. Son defendibles como transición, pero en producción conviene pedir una reconfirmación subiendo `version_minima_valida`.

## 9. Evidencia

Pruebas en `tests/integracion/test_consentimientos.py` (31 pruebas). Entre otras:

- Otorgar guarda estado, fecha, versión y deja historial; revocar guarda fecha y conserva ambas filas.
- Repetir una acción no ensucia el historial; otorgar un canal no habilita el otro.
- Historial y textos son inalterables desde la aplicación.
- Un texto nuevo con cambio de alcance obliga a reconfirmar.
- La auditoría registra el cambio sin RUT, correo, teléfono ni nombre.
- Sin consentimiento no se generan recordatorios; solo sale el canal consentido; revocar cancela lo pendiente y no envía nada.
- El portal rechaza activar un canal sin consentimiento.
- Menores: no consienten por sí mismos; un tercero no puede decidir; el representante verificado sí; al terminar la representación el consentimiento deja de valer; la representación vencida no sirve; recepción rechaza representar a un adulto.
- El panel es solo del Encargado y no muestra identidad.

Eventos de auditoría reales generados por estas operaciones: documento 05, sección 3.

## 10. Limitaciones

- El envío de SMS real depende de un proveedor que no está conectado: hoy el módulo registra el envío en el log con el teléfono enmascarado. El consentimiento sí se exige igual.
- No hay un mecanismo de "dar de baja" desde el propio correo o SMS (enlace o respuesta STOP); la baja se hace en el portal.
- Los textos de consentimiento no pasaron por revisión jurídica; son un borrador técnicamente consistente.
