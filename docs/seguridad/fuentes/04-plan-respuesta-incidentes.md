# Plan de respuesta a incidentes de seguridad

Centro Médico Altavida · IIT421W Seguridad y Protección de Datos · Actividad 4 (Hito 3)

## 1. Propósito y alcance

Este plan define cómo el centro detecta, analiza, contiene, recupera, notifica y aprende de los incidentes que afecten la confidencialidad, integridad o disponibilidad de los datos personales (en especial los de salud) y del servicio. Cubre la aplicación web, su base de datos, las cuentas de pacientes y funcionarios y los servicios que la sostienen. Está implementado en el sistema (módulos de auditoría, alertas, contención e incidentes) y se apoya en procedimientos humanos que el sistema no puede reemplazar.

## 2. Marco normativo y plazos

Los plazos de notificación **no son universales**: dependen de a quién se notifica y de la ley que lo exige. Las fuentes consultadas fueron el texto de las leyes en la Biblioteca del Congreso Nacional (BCN, vía su endpoint de texto) y reseñas de estudios jurídicos; lo marcado "verificar" debe confirmarlo asesoría jurídica antes de operar.

| Autoridad / destinatario | Fundamento | Cuándo corre y cuánto | Estado |
| --- | --- | --- | --- |
| **CSIRT Nacional** (ANCI): alerta temprana | Ley 21.663 (Marco de Ciberseguridad), art. 9 | **3 horas** desde que se toma conocimiento de un incidente con efectos significativos | Reporte vigente desde el 1-mar-2025 (verificar reglamento de reporte) |
| CSIRT Nacional: actualización | Ley 21.663, art. 9 | **72 horas** (24 si es operador de importancia vital, que el centro no es salvo calificación de la ANCI) | Ídem |
| CSIRT Nacional: informe final | Ley 21.663, art. 9 | **15 días corridos** desde la alerta temprana; si el incidente sigue, un informe de situación y el final 15 días después de gestionado | Ídem |
| **Agencia de Protección de Datos Personales** | Ley 21.719, art. 14 sexies | "Por los medios más expeditos posibles y sin dilaciones indebidas" cuando hay destrucción, filtración, pérdida o alteración de datos, o acceso o comunicación no autorizados, **con riesgo razonable** para los titulares. No fija horas | Ley con vigencia legal el 1-dic-2026; hay un proyecto de postergación en el Senado (Boletín 18.623-07) que no pude confirmar como ley, y la Agencia podría no estar constituida aún. Verificar |
| **Titulares afectados** | Ley 21.719, art. 14 sexies | Sin dilaciones indebidas, **solo** si la brecha involucra datos sensibles (la salud lo es), datos de menores de 14 años o datos económicos, y hay riesgo razonable | Ídem |

Por qué el centro está obligado por la Ley 21.663: su artículo 4 enumera como servicio esencial la prestación institucional de salud de hospitales, clínicas, consultorios y **centros médicos**, y el artículo 27 define el efecto significativo como el que puede interrumpir un servicio esencial, afectar la integridad física o la salud de las personas, o afectar sistemas que contengan datos personales.

Metas internas (no son plazos legales): el sistema calcula **72 horas** como meta para avisar a la Agencia y a los titulares, para no quedar en un "sin dilaciones" sin fecha. Antes de la entrada en vigor de la Ley 21.719, la Ley 19.628 vigente no impone un deber de notificar brechas a la autoridad ni a los titulares; aun así, si hay efectos significativos, la Ley 21.663 sí obliga a reportar al CSIRT, y el centro adopta como política notificar a los titulares afectados por los mismos criterios.

## 3. Definiciones: alerta, evento sospechoso, incidente confirmado

| Nivel | Qué es | Quién lo crea | Representación en el sistema |
| --- | --- | --- | --- |
| **Alerta** | Un hecho que una regla automática considera anormal. Puede ser un falso positivo | El sistema (`detectar_alertas`, cada 5–10 minutos) | `AlertaSeguridad` en estado "abierta" |
| **Evento sospechoso** | Una alerta o aviso humano que alguien está analizando y que todavía no se sabe si hubo compromiso | El Encargado de privacidad | Caso `IncidenteSeguridad` con clasificación "sospechoso" |
| **Incidente confirmado** | Hay compromiso demostrado de datos, cuentas o servicio | El Encargado de privacidad, tras el análisis | Caso clasificado "confirmado"; desde aquí corren los plazos legales |
| **Falso positivo** | Se analizó y no hubo compromiso | El Encargado | Clasificación "falso positivo"; se cierra explicando por qué y qué regla ajustar |

El **momento de conocimiento (T0)** es cuando la institución toma conocimiento del hecho: es la fecha del caso (`conocido_en`) y de ella cuentan los plazos de la tabla anterior. La regla práctica: si hay duda razonable de que un incidente puede tener efectos significativos, T0 se registra al abrir el caso y se decide la notificación con la información disponible; es mejor una alerta temprana incompleta que una tardía.

Reglas de detección implementadas (umbrales configurables):

| Regla | Qué detecta | Umbral por defecto | Severidad |
| --- | --- | --- | --- |
| `fuerza_bruta_cuenta` | Intentos fallidos sobre una misma cuenta | 5 en 15 min | Media |
| `rociado_contrasenas` | Un origen probando muchas cuentas | 8 cuentas en 15 min | Alta |
| `acceso_masivo_fichas` | Un funcionario consulta muchas fichas distintas | 15 pacientes en 10 min | Alta |
| `busquedas_excesivas` | Re-identificación masiva | 30 en 10 min | Media |
| `emergencias_repetidas` | Uso reiterado del acceso de emergencia | 3 en 24 h | Alta |
| `denegaciones_repetidas` | Intentos fuera de permisos | 5 en 10 min | Media |
| `exportacion_masiva` | Muchas descargas de datos | 3 en 60 min | Alta |
| `cambio_rol_sensible` | Cambio de rol de una cuenta | Cada ocurrencia | Media |
| `acceso_nocturno` | Consulta de fichas por médicos de 00:00 a 05:00 | Cada cuenta por día | Baja |
| `cadena_rota` | Falla en la integridad del registro de auditoría | Cualquiera | Crítica |

## 4. Roles y responsabilidades por fase

Los cargos son roles, no personas; el centro debe designar titular y suplente de cada uno y mantener sus datos de contacto fuera del sistema (impresos).

| Rol | Quién lo ejerce | Responsabilidad en el plan | Permiso en el sistema |
| --- | --- | --- | --- |
| Coordinador del incidente | Encargado de privacidad | Dirige el caso: clasifica, ordena la evidencia, propone las notificaciones, redacta las comunicaciones, cierra | `gestionar_alertas`, `ver_auditoria`, `gestionar_derechos` |
| Responsable técnico | Administrador del sistema | Ejecuta contención técnica, erradicación y recuperación; **autoriza** las notificaciones junto con la dirección | `gestionar_alertas`, `ejecutar_contencion` |
| Dirección del centro | Director/a médico o gerencia | Decide y firma las comunicaciones externas; asigna recursos; es el contacto con la autoridad. Se ejerce fuera del sistema | Registrado como autorizador cuando una cuenta con `ejecutar_contencion` aprueba |
| Responsable clínico | Médico jefe | Evalúa el impacto en la atención y en la seguridad de los pacientes; define cómo continuar atendiendo con el sistema limitado | — |
| Recepción | Personal administrativo | Atiende a los pacientes durante una contención y deriva consultas; no recibe datos del incidente | — |
| Asesoría legal | Externa | Confirma los plazos, revisa el texto de cada notificación | — |

| Fase | Responsable principal | Apoyo | Salida esperada |
| --- | --- | --- | --- |
| Preparación | Encargado de privacidad | Administrador, dirección | Plan vigente, contactos, accesos, ejercicio anual |
| Detección y análisis | Encargado de privacidad | Administrador | Caso clasificado, T0, criterios de gravedad |
| Contención | Administrador del sistema | Encargado, médico jefe | Compromiso detenido, evidencia preservada con huella |
| Erradicación y recuperación | Administrador del sistema | Encargado | Causa eliminada, servicio restablecido y verificado |
| Notificación y comunicación | Dirección (autoriza); Encargado (ejecuta) | Asesoría legal | Notificaciones enviadas y registradas, o justificación escrita |
| Lecciones aprendidas | Encargado de privacidad | Todos los roles | Informe y mejoras con responsable y fecha |

## 5. Fases

### 5.1 Preparación
- Mantener este plan, los roles con suplentes y una lista impresa de contactos (dirección, administrador, médico jefe, asesoría legal, canal oficial de reporte de la ANCI vigente).
- Mantener operativos los controles que hacen posible responder: auditoría con integridad verificable, detección de alertas programada, contención por interfaz y por comando, copias de respaldo probadas y las llaves en lugar separado.
- Programar `detectar_alertas` cada 5 a 10 minutos y `verificar_auditoria` al menos a diario.
- Hacer un ejercicio de mesa anual con un escenario de esta tabla de reglas y registrar sus lecciones.
- Capacitar a recepción y a los médicos para reportar un hecho sospechoso (correo extraño, equipo perdido, consulta indebida) sin demora.

### 5.2 Detección y análisis
1. Una regla genera una alerta, o una persona reporta un hecho sospechoso. El Encargado la revisa (`EN_REVISION`).
2. Abre un **caso** y fija T0. Si la alerta es falsa, la descarta con nota y no hay caso.
3. Analiza con el registro de auditoría: qué cuenta, qué recursos, desde cuándo, cuánto. Genera el **paquete de evidencia** de la alerta, que obtiene una huella SHA-256.
4. Clasifica: sospechoso, confirmado o falso positivo; y marca los criterios que gobiernan los plazos: si afecta datos personales, continuidad o la salud de las personas; si hay datos sensibles o de menores de 14; si hay riesgo razonable; cuántos titulares aproximadamente y qué categorías de datos.
5. Evalúa la gravedad con la tabla de escalamiento (sección 6).

### 5.3 Contención (preservando la evidencia)
Orden obligatorio: **primero se preserva la evidencia, después se contiene**, porque contener (cerrar sesiones, desactivar cuentas) cambia el estado que se quiere investigar. El sistema lo exige: no permite pasar a "contenido" sin una huella de evidencia.

Acciones disponibles, por interfaz (pantalla de la alerta) o por comando `contener` (cuando la interfaz no está disponible; requiere acceso al servidor):

| Acción | Efecto | Reversible |
| --- | --- | --- |
| Cerrar sesiones de la cuenta | Corta el acceso en curso | — |
| Restringir permisos | Deja la cuenta sin acceso a datos clínicos ni de auditoría | Sí, restaurar |
| Invalidar contraseña | La cuenta no puede volver a entrar sin restablecimiento | Con restablecimiento |
| Desactivar la cuenta | No inicia sesión | Sí, restaurar |
| Cerrar accesos de emergencia | Anula los accesos temporales de un médico | No |
| Modo **solo lectura** del sistema | Se bloquean todos los cambios | Sí |
| Modo **bloqueado** | Solo entra el personal de seguridad | Sí |

Salvaguardas: nadie puede aplicarse una acción a sí mismo, no se puede contener a la única cuenta administradora activa sin una orden explícita, y toda acción queda en la auditoría con quién la ejecutó y por qué vía. Al pasar a modo limitado, recepción informa a los pacientes con el texto de la pantalla "Servicio limitado".

### 5.4 Erradicación y recuperación
- Eliminar la causa: cerrar la vulnerabilidad, rotar credenciales y llaves comprometidas (`rotar_llaves`), revocar accesos, quitar código o cuentas maliciosas.
- Recuperar desde copias íntegras si hubo alteración de datos; **verificar** la integridad del registro de auditoría y de los datos restaurados antes de reabrir.
- Volver a modo normal solo cuando el responsable técnico y el Encargado lo confirmen; mantener vigilancia reforzada en las 72 horas siguientes (umbrales de detección más bajos para las cuentas implicadas).
- Registrar la erradicación y la recuperación como fases del caso.

### 5.5 Notificación y comunicación
**Criterios para decidir** (el sistema muestra qué notificaciones corresponden según lo marcado en el caso):

| Criterio marcado en el caso | Notificación que corresponde |
| --- | --- |
| Efectos significativos (afecta continuidad, salud de personas o sistemas con datos personales) | CSIRT Nacional: alerta temprana 3 h, actualización 72 h, informe final 15 días |
| Afecta datos personales **y** riesgo razonable | Agencia de Protección de Datos |
| Lo anterior **y** datos sensibles (salud) o de menores de 14 | Titulares afectados |
| Ninguno | No se notifica; se escribe una justificación que impide cerrar sin ella |

**Quién autoriza.** Una persona propone la notificación y **otra distinta** con permiso de contención la autoriza (el sistema impide que quien propone autorice). La decisión final y la firma de las comunicaciones externas corresponden a la dirección del centro. La alerta temprana al CSIRT no debe esperar a tener el análisis completo: se envía con lo conocido dentro de las 3 horas y se completa en la actualización.

**Contenido mínimo** de cada comunicación:

| Destinatario | Debe incluir |
| --- | --- |
| CSIRT Nacional | Identificación del centro, momento de conocimiento, descripción del hecho, evaluación inicial de gravedad e impacto, indicadores de compromiso si se tienen, medidas adoptadas (actualización a 72 h), análisis de causa y lecciones (informe final) |
| Agencia | Naturaleza de la vulneración, sus efectos probables, categorías de datos, número aproximado de titulares afectados y medidas adoptadas para gestionarla y evitar que se repita (lo que además se debe registrar internamente) |
| Titulares | Lenguaje claro y sencillo; **qué datos** suyos fueron afectados; consecuencias posibles; medidas que el centro tomó; qué puede hacer la persona para protegerse; a quién contactar. Aviso **individual** a cada titular (a su representante si es menor); si no es posible, un aviso en un medio masivo de alcance nacional |

Reglas: no se informan datos clínicos de nadie por correo, no se adjuntan listados de afectados, y todo texto se revisa con asesoría legal. Cada notificación enviada se **registra** en el caso con fecha y hora (`registrar_notificacion`), y el sistema marca como **vencido** todo plazo que pasa sin envío.

### 5.6 Lecciones aprendidas
Dentro de los 15 días de cerrada la contención, reunión de revisión con todos los roles. Se documenta: causa raíz, cronología, qué detectó y qué dejó pasar el sistema, qué tardó, si se cumplieron los plazos, qué cambia (reglas, umbrales, capacitación, controles) con responsable y fecha. Un falso positivo también se cierra explicando por qué lo fue y qué regla se ajusta. El sistema no deja cerrar sin un texto de lecciones de al menos 40 caracteres.

## 6. Criterios de escalamiento

| Situación | Severidad | Escala a | Plazo máximo para escalar |
| --- | --- | --- | --- |
| Alerta aislada de baja severidad, sin acceso a datos clínicos | Baja | Encargado, en la revisión diaria | 24 h |
| Alerta media o repetida sobre una cuenta | Media | Encargado → Administrador | 4 h |
| Acceso a fichas fuera de la relación terapéutica, exportación masiva, o cuenta privilegiada comprometida | Alta | Encargado + Administrador + Dirección | 1 h |
| Datos de pacientes expuestos o alterados, cadena de auditoría rota, servicio caído por ataque | Crítica | Dirección + asesoría legal, activar notificaciones | Inmediato (corre la alerta temprana de 3 h) |
| Posible daño a la atención de pacientes | Cualquiera | Médico jefe | Inmediato |

Una alerta sube de nivel si se repite, si involucra a una cuenta con permisos sensibles, si el volumen de pacientes crece o si hay indicios de intención.

## 7. Condiciones de cierre

El sistema impide cerrar un caso mientras falte alguna (`pendientes_de_cierre`):

1. Clasificado (confirmado o falso positivo).
2. Si fue confirmado: pasó por contención (con evidencia preservada), erradicación y recuperación.
3. Cada notificación que corresponde está **enviada y registrada**, o existe una justificación escrita de por qué no corresponde.
4. Lecciones aprendidas registradas (causa, falla, mejoras con responsable).
5. Al cerrar, las alertas del caso se cierran (o se descartan si fue un falso positivo).

## 8. Cómo está implementado

| Parte del plan | Componente |
| --- | --- |
| Registro e integridad | `apps/auditoria` (cadena de hashes, triggers) |
| Detección | `alertas.py`, comando `detectar_alertas` |
| Evidencia | `contencion.preservar_evidencia` (JSON con SHA-256) |
| Contención | `contencion.py`, pantalla de alertas, comando `contener`, middleware de modo del sistema |
| Gestión del caso, fases, plazos, autorización, cierre | `incidentes.py`, `views_incidentes.py`, pantalla "Incidentes" |
| Trazabilidad del caso | Eventos `INCIDENTE_CAMBIO` en la auditoría |

## 9. Limitaciones

- El sistema **no notifica por sí mismo** a la ANCI, a la Agencia ni a los titulares: calcula plazos, autoriza y registra, pero el envío es humano.
- No hay turnos de guardia, SIEM, correlación entre fuentes externas ni monitoreo de infraestructura (red, sistema operativo, copias de respaldo). El plan asume que esa capa la provee la infraestructura donde se despliegue.
- Las alertas se calculan al ejecutar `detectar_alertas`; sin una tarea programada la detección es manual. No hay aviso automático por correo o mensajería al Encargado.
- El modelo de roles supone un Encargado y un administrador que son personas distintas; en un centro pequeño la autorización de a dos puede requerir una segunda persona fuera del sistema.
- Los contactos oficiales, el formato exacto del reporte y el reglamento de reporte de incidentes de la ANCI deben confirmarse con las fuentes oficiales vigentes; los plazos de la Ley 21.719 dependen de su entrada en vigor.
- No se ha hecho un ejercicio de mesa real con las personas del centro; la primera ejecución deberá hacerse antes de operar.
