# Diseño del módulo de ejercicio de derechos

Centro Médico Altavida · IIT421W Seguridad y Protección de Datos · Actividad 4 (Hito 3)

## 1. Alcance

El paciente puede ejercer cuatro derechos desde su portal: **acceso**, **portabilidad**, **rectificación** y **supresión**. Cada solicitud es un trámite con estados, plazo, responsable y trazabilidad; no un botón que ejecuta la acción. La razón es de riesgo: cualquiera de estas acciones, hecha por la persona equivocada, entrega datos de salud a un tercero, falsea la identidad de un paciente o destruye evidencia clínica.

| Derecho | Qué hace el sistema | Qué no hace |
| --- | --- | --- |
| Acceso | Entrega todo lo que el centro guarda del paciente, más información sobre el tratamiento (finalidades, conservación, destinatarios, derechos) | No incluye datos de otras personas ni de funcionarios |
| Portabilidad | Misma entrega, en JSON estructurado y de uso común, sin la sección informativa | No transmite los datos a otro prestador; los entrega al titular |
| Rectificación | Corrige nombres, apellidos, correo, teléfono o fecha de nacimiento | No modifica datos clínicos: responde con fundamento y una anotación aclaratoria |
| Supresión | Elimina lo que no hay obligación de conservar y **bloquea** el resto | No borra la ficha clínica antes del plazo legal |

Marco: Ley 21.719 (derechos ARCO y portabilidad; vigencia legal el 1-dic-2026, con un proyecto de postergación en trámite que no pude confirmar como ley), Ley 19.628 vigente, Ley 20.584 y DS 41/2012 (conservación de la ficha por al menos 15 años). El plazo de respuesta está en la configuración (`DERECHOS_PLAZO_DIAS = 30`, días corridos); **debe verificarse contra el texto vigente antes de operar**, y también las reglas de prórroga, que el sistema no implementa.

## 2. Flujo y estados

```
RECIBIDA -> EN_VERIFICACION -> EN_EVALUACION -> RESUELTA -> CERRADA
```

| Etapa | Quién | Qué ocurre | Registro |
| --- | --- | --- | --- |
| Recepción | Paciente (o su representante) | Crea la solicitud desde el portal. Se calcula el plazo y el nivel de verificación requerido | `DERECHO_SOLICITUD` |
| Verificación | Paciente | Confirma su identidad según el nivel (sección 3) | `DERECHO_VERIFICACION` |
| Evaluación | Encargado de privacidad | Revisa la solicitud con códigos seudónimos | `DERECHO_RESOLUCION` |
| Resolución | Encargado de privacidad | Acoge, acoge parcialmente o rechaza **con fundamento**; el sistema ejecuta lo acogido | `RECTIFICACION`, `SUPRESION` o `EXPORTACION_DATOS` según corresponda |
| Cierre | Encargado de privacidad | Cierra; la descarga deja de estar disponible | `DERECHO_RESOLUCION` |

Cada cambio de estado se guarda en `HistorialSolicitud` (inalterable) con fecha y cuenta que lo hizo. La bandeja ordena por plazo y marca las solicitudes vencidas.

Controles del flujo (en `derechos/servicio.py`, no en las pantallas):

- Una tabla de transiciones permitidas rechaza cualquier salto de etapa, aunque alguien envíe una petición armada a mano.
- No se puede acoger nada sin identidad verificada; lo único posible antes es rechazar por "identidad no verificada".
- Un rechazo exige fundamento de una lista cerrada (conservación legal, dato clínico, identidad no verificada, datos de terceros, falta de representación, solicitud infundada, documento requerido).
- Una sola solicitud abierta por persona y tipo, impuesta por una restricción de la base de datos: evita duplicar ejecuciones y saturar el trámite.
- La resolución corre en una transacción: si la ejecución falla, no queda nada a medias (hay una prueba que lo verifica con una supresión que falla a mitad de camino).

## 3. Verificación de identidad proporcional al riesgo

La sesión iniciada no basta. Se exige más según el daño posible:

| Nivel | Se aplica a | Exigencia |
| --- | --- | --- |
| 1 | Rectificar correo o teléfono | Volver a ingresar la contraseña en esa misma petición |
| 2 | Acceso, portabilidad, supresión, y rectificar nombres, apellidos o fecha de nacimiento | Contraseña **y** código de 6 dígitos enviado al correo registrado |

El código: se genera con `secrets`, se guarda solo su huella con llave (no queda en claro ni en la auditoría), vence a los 15 minutos, sirve una vez, admite 5 intentos y se pueden enviar como máximo 3 códigos por solicitud. Superados esos límites, la persona debe acercarse a recepción. Los intentos fallidos quedan como `DENEGADO` en la auditoría y alimentan la detección de alertas.

Si quien solicita es el **representante legal** de un menor, el código y la contraseña son los del representante, y se exige una representación vigente verificada en recepción (documento 01). Un menor no puede solicitar por sí mismo.

Limitación declarada: el código viaja por correo, así que quien controle el correo del paciente podría completar el segundo factor. Es un nivel razonable para este tamaño de centro, pero no equivale a un segundo factor de dispositivo; para solicitudes de supresión de alto impacto una mejora natural es exigir además verificación presencial.

## 4. Autorización y manejo seguro

- **Quién ve qué.** El paciente solo ve sus solicitudes (cualquier otra es un 404). El Encargado de privacidad (permiso `gestionar_derechos`) ve códigos seudónimos y **nunca** la identidad ni el valor propuesto de una rectificación: lo aplica el sistema si acoge. Recepción, médicos y el administrador del sistema no acceden a la bandeja (hay una prueba que lo recorre rol por rol).
- **Separación de funciones.** Quien resuelve (Encargado) no es quien solicita (paciente), y la identidad la verifica el sistema, no una persona que podría equivocarse o ser sobornada.
- **La exportación** se genera al momento de la descarga y no se guarda en el servidor. Está disponible 7 días, hasta 3 descargas, solo para quien solicitó, con `Cache-Control: no-store`; cada descarga queda auditada (evento `EXPORTACION_DATOS` con el conteo, sin contenido). Al cerrar la solicitud la descarga se invalida.
- **El texto libre** de la respuesta al titular se guarda cifrado y se advierte al Encargado que no escriba datos personales ni clínicos en él.
- La detección de alertas incluye una regla de exportaciones masivas (3 en 60 minutos por la misma cuenta).

## 5. Reglas de negocio de cada derecho

### Acceso y portabilidad
Al acoger se habilita la descarga. El contenido es: identidad (descifrada), datos de contexto, historial médico, diagnósticos, recetas con sus ítems, resultados de exámenes con las observaciones médicas, citas, historial de consentimientos y de solicitudes. No incluye nombres de médicos ni de funcionarios, ni datos de otras personas.

### Rectificación
Solo se aplican campos de una lista cerrada. Antes de aplicar un correo se verifica que no lo use otra cuenta, y al cambiarlo se actualiza el índice de inicio de sesión. Un dato **clínico** no se corrige borrando: la ficha es un registro médico-legal. El Encargado responde "acogida parcial" o "rechazada" con el fundamento `DATO_CLINICO` y la indicación de que se agregará una anotación aclaratoria (la anotación la realiza el médico tratante; el sistema no automatiza ese paso).

### Supresión
Es el caso más delicado, porque dos obligaciones chocan: el derecho a eliminar y la obligación de conservar la ficha al menos 15 años desde la última atención. El sistema hace lo siguiente:

1. Revoca todos los consentimientos (queda en el historial).
2. Elimina avisos, recordatorios, preferencias y órdenes externas adjuntas.
3. Desactiva la cuenta del portal, anula su contraseña, borra sus índices de acceso y cierra sus sesiones.
4. Si el paciente tiene ficha, citas, recetas o resultados, la resolución pasa automáticamente a **parcial** con fundamento "conservación legal". Se explica la fecha hasta la cual se conserva (última atención + 15 años) y los datos quedan **bloqueados**: marcados con fecha de bloqueo, sin cuenta, sin recordatorios, sin posibilidad de nuevos consentimientos ni solicitudes.
5. Si no hay ningún dato clínico, se elimina también el diccionario de identidad, y la persona deja de ser identificable.

Los datos de gestión no clínicos (contacto, citas) se conservan 24 meses desde la última atención, según la política de retención del Hito 2. Esa eliminación diferida no está programada todavía en una tarea periódica (ver limitaciones).

**Punto honesto sobre la dirección.** El Hito 2 eliminó el campo `dirección` por minimización, pero el DS 41/2012 (art. 6 letra a) incluye el domicilio entre los datos mínimos de la ficha. Se mantuvo la decisión de no recolectarla, con la justificación de que hoy ningún proceso del sistema la usa, y se deja documentado que, si el centro opta por cumplir la norma al pie de la letra, el campo debe volver a la ficha.

## 6. Pantallas

- **Mis derechos** (paciente): lista de solicitudes con tipo, estado y plazo, y botón de nueva solicitud.
- **Nueva solicitud:** tipo, para quién (el paciente o un representado) y, si corresponde, qué dato corregir.
- **Detalle:** formulario de verificación (contraseña y código), reenvío de código, respuesta fundamentada, descarga y seguimiento por estados.
- **Bandeja del Encargado** y **gestión de la solicitud:** criterios de identidad, datos clínicos que obligan a conservar, formulario de resolución e historial.

## 7. Evidencia

Pruebas en `tests/integracion/test_derechos.py` (34 pruebas), entre ellas:

- Plazo, historial y niveles de verificación por tipo; una sola solicitud abierta por tipo.
- Código por correo, no guardado ni auditado en claro; clave incorrecta denegada y registrada; intentos limitados; código vencido y de un solo uso; límite de envíos.
- No se resuelve sin verificar identidad; rechazo exige fundamento; no se resuelve dos veces ni se cierra antes de tiempo; historial inalterable.
- Descarga: entrega solo los datos propios, cuenta cada descarga, la audita sin contenido, vence y se limita; otro paciente recibe 404.
- Rectificación: se aplica al acoger y el inicio de sesión sigue al correo; no se aplica si se rechaza; un correo ya usado se rechaza sin cambios; un dato clínico no se modifica.
- Supresión: con ficha es parcial y bloquea, conserva los diagnósticos, desactiva la cuenta y revoca consentimientos; sin datos clínicos elimina la identidad; un bloqueado no puede consentir ni solicitar; una falla no deja cambios a medias.
- Menores: no solicitan por sí mismos; el representante verificado sí y el código le llega a él; una representación vencida no sirve.
- Solo el Encargado gestiona; los demás roles reciben 403 en cada ruta; el Encargado no ve identidad ni valores propuestos.
- Flujo completo por pantalla, con los cinco estados en orden.

Eventos de auditoría reales: documento 05, sección 3.

## 8. Limitaciones

- No se programó la eliminación automática de los datos de gestión a los 24 meses ni de la ficha a los 15 años (hoy `purgar_datos` cubre avisos, recordatorios y órdenes externas). Hay que agregar esa tarea y probarla antes de operar.
- No se implementa prórroga del plazo ni la notificación automática al titular de los cambios de estado; el titular los ve al entrar al portal.
- Oposición y limitación del tratamiento no están implementadas como solicitud; la Ley 21.719 las contempla.
- Los datos copiados en respaldos de base de datos fuera de la aplicación no se tocan con una supresión; requieren la política de respaldos del centro.
- El formato JSON es de uso común y legible por máquinas, pero no sigue un estándar clínico (por ejemplo HL7 FHIR).
