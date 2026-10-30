# Evidencia de pruebas y justificación técnica final

Centro Médico Altavida · IIT421W Seguridad y Protección de Datos · Actividad 4 (Hito 3)

## 1. Qué se entrega

| Entregable pedido | Dónde está |
| --- | --- |
| Diseño del módulo de consentimiento | Documento 01 |
| Diseño del ejercicio de derechos | Documento 02 |
| Diseño del registro de auditoría | Documento 03 |
| Plan de respuesta a incidentes | Documento 04 |
| Código actualizado e integrado | Aplicaciones `consentimientos`, `derechos` y `auditoria` (con alertas, contención e incidentes), más los cambios en `usuarios`, `pacientes` y `notificaciones`; rama `leo` |
| Evidencia de pruebas y eventos de auditoría | Esta sección y la 3 |
| Justificación técnica final | Sección 5 |

## 2. Resultado de las pruebas

Se ejecutó `python manage.py test tests`: **340 pruebas, todas pasan**. Distribución de las pruebas relacionadas con esta actividad y con los controles de los que dependen:

| Módulo de pruebas | Pruebas | Qué demuestra |
| --- | --- | --- |
| `test_consentimientos` | 31 | Estado, historial, revocación efectiva en recordatorios, un permiso no habilita otro, menores y representantes, control de acceso |
| `test_derechos` | 34 | Flujo por estados, verificación proporcional, código de un solo uso, ejecución de los cuatro derechos, descarga limitada, control de acceso rol por rol |
| `test_auditoria` | 40 | Cadena de hashes, triggers, inmutabilidad, lista blanca de claves, redacción de datos personales, lectura restringida y auditada |
| `test_alertas_contencion` | 37 | Reglas de detección, ciclo de vida de la alerta, evidencia con huella, contención por interfaz y por comando, modo del sistema |
| `test_incidentes` | 21 | Fases, plazos de 3 h / 72 h / 15 días, autorización de a dos, condiciones de cierre, control de acceso |
| `test_rbac` | 27 | Permisos por rol, incluidos los de privacidad |
| `test_privacidad`, `test_retencion_anonimizacion`, `test_rotacion_llaves`, `test_endurecimiento` | 35 | Seudonimización, cifrado, retención, rotación de llaves, endurecimiento de sesión y errores |

### Controles que no se pueden saltar con una petición directa o con la base

Cada control está en la capa que lo hace cumplir, no solo en la pantalla:

| Intento de saltarse el control | Qué lo detiene | Prueba |
| --- | --- | --- |
| Enviar a mano la petición de resolver, cerrar o autorizar sin ser Encargado | Permiso del servidor (403) en cada ruta; se probó con los cinco roles restantes | `test_solo_el_encargado_gestiona_las_solicitudes`, `test_solo_seguridad_ve_los_casos` |
| Resolver una solicitud sin verificar la identidad | Regla del servicio, no de la pantalla | `test_no_se_puede_resolver_sin_verificar_identidad` |
| Saltar etapas de una solicitud o de un caso | Tabla de transiciones permitidas | `test_no_se_resuelve_dos_veces_ni_se_cierra_antes_de_tiempo` |
| Descargar los datos de otro paciente | La solicitud se busca por su titular: otro paciente recibe 404 | `test_otro_paciente_no_puede_ver_ni_descargar_una_solicitud_ajena` |
| Decidir un consentimiento por un menor sin ser su representante | Regla del servicio más evento `DENEGADO` | `test_un_tercero_sin_representacion_no_puede_decidir`, `test_el_representante_gestiona_desde_su_portal_y_otro_paciente_no` |
| Activar un canal de recordatorios sin consentimiento | Rechazo en el servidor y revisión al generar y al enviar | `test_el_portal_no_deja_activar_un_canal_sin_consentimiento` |
| Autorizar su propia propuesta de notificación | Regla del servicio | `test_exige_propuesta_y_autorizacion_de_otra_persona` |
| Cerrar un incidente con notificaciones o lecciones pendientes | `pendientes_de_cierre` | `test_no_cierra_con_pendientes` |
| Modificar o borrar un evento de auditoría con SQL directo | Triggers de la base de datos | `test_alterar_un_evento_rompe_la_cadena` y las de inmutabilidad |
| Cambiar un campo de un evento sin que se note | Hash que cubre todos los campos | `test_alterar_cualquier_campo_rompe_la_cadena` |
| Dejar una supresión a medias | Transacción única | `test_si_falla_la_ejecucion_no_queda_nada_a_medias` |
| Reutilizar o adivinar el código de verificación | Un uso, 15 minutos, 5 intentos, 3 envíos | `test_codigo_vencido_y_de_un_solo_uso`, `test_codigo_incorrecto_y_limite_de_intentos` |

## 3. Eventos de auditoría de ejemplo

Los eventos siguientes **no son inventados**: se generaron ejecutando un escenario completo (`escenario.py`) sobre una base de pruebas temporal, con el código real de los tres módulos. El escenario hace, en orden: una paciente otorga y revoca el consentimiento del correo; pide acceso a sus datos, falla la verificación una vez, la completa con el código recibido, el Encargado acoge, ella descarga y se cierra; pide cambiar su teléfono; un médico intenta leer la auditoría y es denegado; el Encargado la lee; el mismo médico consulta 60 fichas distintas, lo que dispara una alerta; se cierran sus sesiones; se abre un incidente, se clasifica, se preserva la evidencia, se propone y autoriza (por otra persona) la notificación y se registra la alerta temprana al CSIRT. Los identificadores de paciente son códigos seudónimos aleatorios. Se omiten los 60 eventos de consulta de fichas, pero quedaron en la cadena (total 86 eventos) y la verificación final dio `íntegra`.

```
{{EVENTOS}}
```

Qué muestran estos eventos:

- No hay RUT, nombre, correo, teléfono, contraseñas ni el código de 6 dígitos; el valor del teléfono nuevo no aparece, solo el nombre del campo.
- Cada paso de una solicitud de derechos queda con su estado; la verificación fallida aparece como `DENEGADO` y la completada como `OK` con el método usado.
- La lectura no autorizada de la auditoría aparece como `ACCESO_DENEGADO` del rol `MEDICO`.
- La alerta del acceso masivo se generó sola (regla `acceso_masivo_fichas`, cantidad 60).
- La autorización de la notificación está hecha por `ADMIN_SISTEMA` y la propuesta por `PRIVACIDAD`: personas distintas.

## 4. Hallazgos durante la implementación

Esta actividad se hizo revisando también lo anterior, y salieron cuatro defectos reales que estaban en el código ya integrado:

| Hallazgo | Impacto | Corrección |
| --- | --- | --- |
| La bandera de depuración estaba invertida: `DEBUG` quedaba activo salvo que se configurara lo contrario | Páginas de error con detalles y variables en producción | Pasa a activarse solo con `DJANGO_DEBUG=1`; las pruebas se aislaron del archivo `.env` |
| `.env.example` había sido borrado y había un archivo temporal de Word versionado | Faltaba la plantilla de configuración | Restaurado y limpio |
| Una hora local usada para calcular el hash hacía que la verificación fallara tras ir y volver de la base | Falsos positivos de cadena rota | Fecha normalizada a UTC y prueba de regresión |
| Un comentario mal ubicado sacó `actor_id` del cálculo del hash | Cambiar quién hizo una acción no rompía la cadena | Corregido y cubierto por una prueba que altera cada columna |

El tercero lo encontró una prueba de integridad; el cuarto se descubrió al verificar la base de desarrollo real y no una de prueba, lo que muestra el valor de verificar también con datos reales.

## 5. Justificación técnica final

**Consentimiento.** Se redujo a lo que realmente depende de él. Pedir una casilla general para la atención clínica habría sido jurídicamente débil (no es libre si no se puede rechazar sin perder la atención) y habría ocultado el verdadero fundamento. Con una finalidad y un texto versionado por canal, el consentimiento es específico, informado y demostrable, y la revocación tiene efecto real porque se revisa en el momento del envío y no solo al generar el aviso. El menor se resuelve con representación verificada en persona y con una dependencia explícita: si termina la representación, termina el consentimiento.

**Derechos.** Se trataron como trámites de riesgo y no como funciones. La verificación crece con el daño posible; la resolución la hace una función independiente que no ve identidad; las reglas viven en el servicio, de modo que ninguna pantalla puede saltárselas; y la supresión reconoce que la obligación de conservar la ficha prevalece, eliminando y bloqueando lo que corresponde y explicando por escrito el fundamento. Es el diseño que mejor equilibra el derecho del titular con las obligaciones sanitarias.

**Auditoría.** La decisión central es registrar mucho de "quién, qué y cuándo" y casi nada de "qué contenía". Eso permite detectar abusos y reconstruir hechos sin crear una segunda copia de datos sensibles. La integridad no depende de la buena fe: hash encadenado con llave propia, triggers, lectura restringida a una función separada del administrador y auditoría de la propia lectura.

**Respuesta a incidentes.** Se separó alerta, evento sospechoso e incidente confirmado para no notificar por reflejo ni por omisión, se ancló cada plazo a un momento de conocimiento registrado, y se hizo que el sistema calcule los plazos de la Ley 21.663 (que sí está vigente y sí aplica a un centro médico) y deje constancia de las decisiones sobre la Ley 21.719 (cuya vigencia está en discusión). El cierre exige notificaciones registradas o justificadas y lecciones escritas; la autorización es de a dos.

**Coherencia entre los módulos.** Los cuatro comparten el mismo registro de auditoría y el mismo modelo de roles: el Encargado de privacidad es quien lee la auditoría, gestiona los derechos, ve los consentimientos y coordina los incidentes; el administrador mantiene la infraestructura y ejecuta la contención técnica pero no accede a lo clínico ni a la auditoría. Una revocación de consentimiento, una supresión y un incidente dejan todos eventos del mismo tipo, con el mismo formato y la misma protección.

## 6. Limitaciones y pendientes antes de operar

Declaradas con franqueza porque la actividad pide hacerlo cuando falta infraestructura externa:

1. **Proveedor de SMS inexistente.** El SMS solo se registra en el log (con teléfono enmascarado). El consentimiento sí se exige.
2. **Correo.** El código de verificación y los recordatorios usan el correo del servidor de Django; en producción hay que configurar un servicio de correo con credenciales y control de entrega.
3. **Triggers de auditoría probados solo en SQLite.** La variante de PostgreSQL está escrita y no se probó.
4. **Llave de auditoría sin custodia externa.** Quien tenga base y llave puede recalcular la cadena. Falta anclar el último hash fuera del servidor y usar un gestor de secretos.
5. **Tareas programadas no incluidas:** `detectar_alertas`, `verificar_auditoria`, `purgar_datos`, `purgar_auditoria` y `enviar_recordatorios` existen como comandos, pero no hay un programador de tareas configurado, y no está programada la eliminación de datos de gestión a 24 meses ni de fichas a los 15 años.
6. **Fundamento legal por confirmar.** Plazo de 30 días para responder derechos y prórroga; edad de consentimiento de menores (14 vs 18); vigencia de la Ley 21.719 ante el proyecto de postergación; reglamento de reporte de la ANCI y su canal. Todos están indicados como "verificar" en los documentos.
7. **Domicilio.** El DS 41/2012 lo incluye entre los datos mínimos de la ficha y el sistema no lo recolecta; la decisión del Hito 2 se mantuvo con una justificación honesta y puede revertirse.
8. **Sin notificaciones automáticas** a la ANCI, la Agencia ni los titulares, y sin guardia 24/7.
9. **Sin ejercicio de mesa** ni revisión jurídica de los textos de consentimiento y de las comunicaciones.
10. **Un hallazgo en la base de desarrollo.** El segundo evento de auditoría de esa base se creó mientras el defecto del hash estaba presente y su cadena no verifica. Es un dato de prueba; en una base nueva o de producción no ocurre. La forma correcta de resolverlo es reiniciar la base de desarrollo, ya que la purga normal no puede borrar eventos de menos de 24 meses.

## 7. Fuentes

- Ley 21.719, texto en la Biblioteca del Congreso Nacional (art. 14 sexies, vulneraciones de seguridad).
- Ley 21.663, Marco de Ciberseguridad, texto en la Biblioteca del Congreso Nacional (arts. 4, 9 y 27).
- Reseñas de estudios jurídicos sobre el reglamento de reporte de incidentes (Cariola, AZ, Carey) y sobre el proyecto de postergación de la Ley 21.719 (Boletín 18.623-07): consultadas, **no verificadas contra el texto oficial**.
- DS 41/2012 del Ministerio de Salud (Reglamento sobre fichas clínicas) y Ley 20.584, según el análisis del Hito 1.
