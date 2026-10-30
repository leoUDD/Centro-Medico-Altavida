# Diseño del registro de auditoría

Centro Médico Altavida · IIT421W Seguridad y Protección de Datos · Actividad 4 (Hito 3)

## 1. Para qué sirve y qué no es

El registro de auditoría permite reconstruir **quién hizo qué, sobre qué recurso, cuándo y con qué resultado**, detectar usos indebidos (alertas) y respaldar la respuesta a incidentes y los reclamos de los titulares. No es un respaldo de datos ni una copia de las fichas, y no debe permitir reconstruir información clínica: su contenido es deliberadamente pobre en datos personales.

Se distingue de las bitácoras de acceso que ya existían (`AccesoFicha`, `AccesoIdentidad`), que quedan como registro funcional del módulo clínico. La auditoría es transversal, tiene integridad verificable y es lo que consultan el Encargado de privacidad y la respuesta a incidentes.

## 2. Qué se registra

El catálogo está cerrado en `Operacion` (35 tipos); un evento no puede inventar tipos nuevos. Agrupados:

| Grupo | Eventos |
| --- | --- |
| Sesión y cuentas | Inicio de sesión, intento fallido, bloqueo por intentos, cierre de sesión, cuenta creada, cambio de rol, cuenta activada o desactivada |
| Datos clínicos | Consulta y creación de ficha, registro de diagnóstico, observación de examen, emisión de receta, acceso de emergencia |
| Identidad y agenda | Búsqueda de pacientes (re-identificación), consulta de la agenda, corrección de contacto, reserva y cambio de cita |
| Consentimiento y derechos | Cambio de consentimiento, solicitud, verificación y resolución de derechos, exportación de datos, rectificación, supresión |
| Controles | Acceso denegado por permisos, alerta generada y revisada, acción de contención, gestión de incidentes |
| Auditoría y sistema | Consulta, verificación y purga del propio registro; retención aplicada; rotación de llaves |

Atributos de cada evento (tabla `EventoAuditoria`):

| Atributo | Contenido | Nota de minimización |
| --- | --- | --- |
| `uid`, `id` | Identificador único y secuencia | Sin significado personal |
| `fecha` | Fecha y hora UTC | Del servidor |
| `actor_id`, `actor_rol` | Cuenta y rol de quien actuó | Id interno, no nombre ni correo |
| `actor_ref` | Para quien no tiene sesión (intento de login): huella con llave de lo que escribió | No el correo ni el RUT |
| `operacion` | Una de las del catálogo | |
| `recurso_tipo`, `recurso_ref` | Qué se tocó y cuál (código seudónimo del paciente, número de cuenta, código de solicitud) | Nunca RUT ni nombre |
| `resultado` | OK, DENEGADO o FALLIDO | |
| `ip_hash` | HMAC de la IP, 16 caracteres | La IP en claro no se guarda; permite correlacionar sin identificar |
| `detalle` | JSON con claves de una lista permitida (cantidad, finalidad, campo, estado anterior y nuevo, regla, código de motivo, tipo, versión, canal, formato, código de solicitud, método, acción…) y valores cortos | Ver sección 3 |
| `hash_anterior`, `hash` | Eslabón de la cadena de integridad | Ver sección 4 |

## 3. Qué NO se registra (y por qué)

Lista explícita, pedida por la actividad. Se aplica por diseño: el campo `detalle` solo admite claves de una lista blanca, descarta cualquier otra, trunca los valores a 80 caracteres y enmascara RUT, correos y teléfonos que se cuelen en un texto.

| No se registra | Motivo |
| --- | --- |
| Contenido clínico: diagnósticos, tratamientos, recetas, resultados, observaciones, motivos de consulta | Un registro con contenido clínico sería otra copia de la ficha, con menos protección que la original |
| Valores de campos modificados, antes ni después (solo el **nombre** del campo) | Un cambio de teléfono no debe dejar el teléfono anterior ni el nuevo en un registro de larga duración |
| RUT, nombres, correos y teléfonos en claro | Identifican; el paciente aparece por su código seudónimo y se enmascara lo que se cuele |
| Contraseñas, códigos de verificación, tokens, llaves y cookies de sesión | Riesgo directo de suplantación. Hay además una lista de nombres prohibidos (clave, contraseña, token, llave, secreto, sesión, cookie) que se descartan aunque alguien los agregue a la lista blanca |
| Dirección IP en claro y agente de navegador | Minimización; la huella permite agrupar intentos del mismo origen sin identificar a nadie |
| Cuerpo de las peticiones y respuestas HTTP | Contendría los datos que se quiere no duplicar |
| Texto de los recordatorios, de los consentimientos aceptados y de las respuestas a solicitudes de derechos | Solo se guardan códigos, versión y estado |
| Valor propuesto en una rectificación | Se aplica sin pasar por la auditoría |
| Copias de documentos de representantes legales | Solo se anota qué documento se revisó |
| Lecturas que un paciente hace de sus propios datos en el portal | No son un riesgo de acceso indebido y multiplicarían el volumen; sí se audita lo que sale del sistema (exportaciones) y cualquier intento denegado |
| Eventos de lectura de datos no clínicos de poco riesgo (listas de notificaciones, catálogos) | Ruido sin valor de detección |

Consecuencia que se acepta: la auditoría **no puede responder qué valor tenía un dato** antes de un cambio, solo que cambió, quién y cuándo. Esa pregunta se responde, si corresponde, con la ficha y las solicitudes de derechos.

## 4. Protección contra modificación, eliminación y acceso no autorizado

Capas, de afuera hacia adentro:

1. **Aplicación.** El administrador de consultas del modelo bloquea `update` y `delete`, y el evento no admite `save` si ya existe. El registro se escribe únicamente con `servicio.registrar`.
2. **Base de datos.** Cuatro triggers (SQLite en esta entrega) rechazan `UPDATE` de eventos, `DELETE` de eventos con menos de 24 meses y cualquier cambio o borrado de los puntos de control, **incluso con SQL directo**. Hay una variante equivalente para PostgreSQL escrita pero **no probada**.
3. **Cadena de integridad.** Cada evento incluye en su hash el hash del anterior, calculado con HMAC-SHA256 y una llave propia (`CLAVE_AUDITORIA`, distinta de las llaves de cifrado e identidad y obligatoriamente diferente de ellas). Alterar, borrar o insertar un evento en el medio rompe la cadena desde ese punto, y falsificarlo requiere la llave. El hash cubre todos los campos, incluidos actor, rol, recurso, resultado, huella de IP, detalle y fecha (la fecha se normaliza a UTC para que el cálculo no dependa de la zona horaria).
4. **Verificación.** `verificar_auditoria` y el botón de la pantalla recorren la cadena. Una regla de detección crea una alerta crítica si encuentra una cadena rota, y verificar queda auditado.
5. **Acceso de lectura.** Solo el rol **Encargado de privacidad** (permiso `ver_auditoria`) puede leer el registro. El administrador del sistema, que mantiene los servidores, tiene **prohibida** la lectura por diseño (control de quién vigila al que administra), el médico y el personal administrativo tampoco, y cada consulta queda auditada. Un intento denegado es en sí mismo un evento y alimenta la regla de denegaciones repetidas.
6. **Quién puede borrar.** Nadie desde la aplicación. La única vía es el comando `purgar_auditoria` (retención), que elimina solo eventos contiguos desde el inicio de la cadena que pasaron 24 meses y deja un **punto de control** (último id eliminado, hash del último y cantidad), de modo que la verificación siga siendo posible después de la purga. Los puntos de control tampoco se modifican.

Fallo seguro: si el registro de un evento falla, **no se aborta la operación auditada** (el paciente no debe quedar sin atención por un fallo del registro); el error se escribe en el log del servidor para que se investigue. Es una decisión consciente de disponibilidad sobre exhaustividad, y deja abierta la posibilidad de huecos, que el log técnico permite detectar.

## 5. Quién puede leer, para qué y con qué límites

| Rol | Lee la auditoría | Observación |
| --- | --- | --- |
| Encargado de privacidad | Sí (filtros por operación, resultado, actor, recurso y fechas, paginado) | Ve códigos seudónimos y números de cuenta, nunca identidad |
| Administrador del sistema | No | Gestiona alertas y contención, pero no lee el registro |
| Médico, administrativo, paciente | No | Reciben 403 y el intento se registra |

Para investigar una alerta, el Encargado puede generar un **paquete de evidencia** (JSON con los eventos del caso) con su huella SHA-256, que queda anotada en la alerta; esa huella es la que exige el plan de incidentes antes de dar por contenido un caso.

## 6. Retención y eliminación segura

- **Plazo:** 24 meses (`AUDITORIA_RETENCION_MESES`). Justificación: cubre un ciclo completo de reclamos, fiscalización y revisión anual, sin conservar indefinidamente un registro de uso de datos personales. La base de datos impone ese mínimo con el trigger; el plazo no es modificable desde la aplicación sin cambiar la migración.
- **Cómo se elimina:** con `purgar_auditoria`, en bloque desde el evento más antiguo, dentro de una transacción que crea el punto de control antes de borrar. No hay borrado selectivo (no se puede eliminar un solo evento incómodo).
- **Segura:** en una base SQLite o PostgreSQL el `DELETE` no sobrescribe físicamente los datos. La eliminación segura real depende del cifrado del disco y de la política de respaldos del servidor. Como el contenido ya es seudónimo y sin datos clínicos, el riesgo residual es bajo, pero no es cero.
- Los respaldos que contengan eventos vencidos deben destruirse bajo el mismo plazo; esto es un procedimiento operativo, no código.

## 7. Justificación de las decisiones

- **Hash encadenado en vez de solo permisos:** los permisos protegen contra personal sin acceso a la base, pero no contra un administrador con acceso total; la cadena vuelve evidente la alteración.
- **Llave separada:** si se filtra la llave de cifrado de fichas no se debe poder falsificar la auditoría, ni al revés.
- **Lista blanca de claves del detalle:** en un registro que dura años, es más seguro prohibir todo y permitir lo mínimo que bloquear lo peligroso.
- **Auditar la lectura de la auditoría:** el control se aplica también a quien controla.
- **Separar al Encargado del administrador:** quien opera la infraestructura no es quien vigila su uso de los datos.

## 8. Evidencia

Pruebas en `tests/integracion/test_auditoria.py` (40 pruebas) y `test_alertas_contencion.py` (37), entre ellas: cada campo del evento está cubierto por el hash (una prueba altera cada columna por SQL directo y exige que la verificación falle); alterar o borrar un evento del medio rompe la cadena; un evento falsificado sin llave no pasa; los triggers rechazan modificar y borrar con SQL directo; la purga respeta el mínimo, deja punto de control y la cadena sigue verificando; el detalle descarta claves no permitidas, claves con nombres de secretos y datos personales enmascarados; solo el Encargado lee y cada lectura se audita; las denegaciones se registran.

Durante esta entrega esa prueba por columna detectó un defecto real que las demás no veían: un comentario mal ubicado había dejado el campo `actor_id` fuera del cálculo del hash, de modo que cambiar quién hizo una acción no rompía la cadena. Se corrigió y quedó cubierto por la prueba.

Ejemplos de eventos reales: documento 05, sección 3.

## 9. Limitaciones

- Quien tenga a la vez acceso de escritura a la base **y** la llave `CLAVE_AUDITORIA` podría recalcular toda la cadena. Mitigaciones no implementadas: anclar periódicamente el último hash fuera del servidor (correo al Encargado, papel, sellado de tiempo externo) y guardar la llave en un gestor de secretos separado.
- La hora es la del servidor; un reloj manipulado afectaría las fechas.
- Triggers probados solo en SQLite; la variante de PostgreSQL requiere pruebas antes de producción.
- La verificación recorre toda la cadena; con años de eventos conviene verificar por tramos o programarla fuera de horario.
- El registro es "fail-open": un fallo al escribir no detiene la operación y puede dejar un hueco registrado solo en el log técnico.
