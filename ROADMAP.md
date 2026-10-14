# PAGDOC | Plan de desarrollo y criterios de avance

Actualización: 14 de octubre de 2026.

## Entregado y verificado
- Landing page pública y panel demostrativo multi-módulo con datos 100 % ficticios mediante GitHub Pages.
- API privada FastAPI multiempresa, todavía **no desplegada para uso real**.
- Gestión de usuarios, proyectos, trabajadores, vehículos, documentos y dashboard.
- Roles `admin`, `editor` y `viewer` con autorización por operación y separación por tenant.
- Contraseñas Argon2, sesiones opacas revocables, cookies seguras, CSRF y límite de intentos de acceso.
- MFA TOTP y recuperación administrativa de acceso; los códigos de recuperación de autoservicio siguen pendientes.
- PostgreSQL mediante `psycopg` y esquema Alembic versionado hasta `0008_retention_policy`.
- Migraciones completas validadas automáticamente tanto sobre SQLite limpia como PostgreSQL 17.
- Pruebas concurrentes reales en PostgreSQL para versionado de archivos y cadena de auditoría.
- Copia de seguridad y restauración PostgreSQL ejecutadas y verificadas en CI.
- Requisitos documentales configurables, vigencias y motor de estados/alertas internas opt-in.
- Historial de cambios de metadatos documentales por tenant.
- Búsqueda paginada de documentos con filtros por estado, tipo, proyecto y texto.
- Almacenamiento local cifrado de prototipo, validación de firma/tipo/tamaño y registro inmutable de versiones binarias.
- Gateway de ingreso fail-closed: un archivo solo puede almacenarse después de validación y veredicto limpio de un scanner inyectado.
- El gateway binario permanece sin endpoint HTTP hasta disponer de scanner antimalware real y almacenamiento privado de producción.
- Auditoría sensible con sellos HMAC encadenados por tenant y verificación de manipulación dentro del tramo sellado.
- La auditoría no se presenta como WORM/inmutable: falta un anclaje externo para detectar eliminación del extremo final de la cadena.
- Endpoint de readiness con verificación de base y revisión Alembic en staging/producción.
- Cabeceras API reforzadas, incluyendo CSP restrictiva y HSTS en staging/producción.
- Motor de retención no destructivo: reglas por tipo documental, vista previa de candidatos y `legal hold` por documento.
- La retención **no elimina nada automáticamente**; cualquier eliminación real queda bloqueada hasta aprobación de política y controles de producción.
- Prueba end-to-end del servidor privado con tenant, usuario, proyecto y documentos exclusivamente ficticios.
- Guard automático para impedir artefactos privados y patrones comunes de secretos en el repositorio público.

## Evidencia automática actual
La validación base anterior a la beta operativa finalizó en verde. La suite principal aprobó **121 pruebas**, el smoke test privado ficticio aprobó **1 prueba** y las pruebas de concurrencia PostgreSQL aprobaron **2 pruebas**, para un total de **124 pruebas aprobadas**. Las migraciones `0001` a `0008` se aplicaron correctamente sobre SQLite y PostgreSQL, y la restauración PostgreSQL fue validada dentro del mismo workflow.

## Planificador de personal
- Calendario mensual del equipo o por colaborador con datos ficticios.
- Asignación por día/período de terreno, descanso y servicio; eliminación de asignación mediante estado sin asignar.
- Guardado local en navegador y exportación CSV del mes seleccionado.
- Pendiente de producción: modelo de planificación en servidor, permisos, auditoría y sincronización multiusuario.

## Siguiente bloque técnico antes de producción
1. Integrar un scanner antimalware real y almacenamiento privado de objetos, manteniendo el gateway fail-closed.
2. Diseñar y probar endpoints binarios privados de carga/descarga solo después de completar el punto anterior.
3. Separar y gestionar secretos/llaves mediante infraestructura privada autorizada, con rotación y respaldo seguro.
4. Incorporar monitoreo operativo, métricas, alertas de servicio y anclaje externo de auditoría.
5. Ejecutar pruebas de rendimiento, accesibilidad y seguridad ofensiva controlada.
6. Completar y aprobar formalmente privacidad, retención, eliminación y respuesta a incidentes; el motor actual solo genera vistas previas y legal holds.
7. Desplegar una beta privada únicamente con datos ficticios, después de validar infraestructura y costos.
8. Incorporar información real solamente con autorización expresa y después de aprobar seguridad/privacidad.

## Reglas permanentes del proyecto
- Costo inicial aprobado: **$0 CLP**. No contratar recursos ni generar cobros sin aprobación explícita.
- Nunca subir datos reales de trabajadores, clientes o MUFAS CHILE al repositorio público.
- La demo pública no autentica usuarios ni almacena documentación.
- El backend privado no está habilitado para producción con datos reales.
- No enviar correos, invitaciones ni mensajes a terceros sin autorización del propietario.
- No publicar secretos, contraseñas, tokens, archivos `.env`, bases de datos ni documentos privados.
- Las funciones destructivas de retención/eliminación permanecen deshabilitadas hasta aprobación formal.

## Criterios para declarar PAGDOC 100 % operativo
Cada criterio debe demostrarse con evidencia técnica; escribir código por sí solo no lo completa.

- [x] Sitio comercial publicado mediante HTTPS en GitHub Pages.
- [x] Demo pública multi-módulo con datos ficticios y exportación CSV.
- [x] CI de backend en verde con autorización y aislamiento multiempresa.
- [x] Gestión base de usuarios, roles, proyectos, trabajadores, vehículos y documentos.
- [x] CSRF, cookies seguras, sesiones revocables y protección frente a intentos repetidos de login.
- [x] MFA TOTP y recuperación administrativa de acceso.
- [x] Migraciones Alembic verificadas en SQLite y PostgreSQL.
- [x] Concurrencia crítica verificada en PostgreSQL.
- [x] Reglas configurables de requisitos/vigencias y alertas internas opt-in.
- [x] Copia de seguridad y restauración PostgreSQL validadas en CI.
- [x] Historial de metadatos documentales y registro de versiones binarias cifradas en la capa de servicio.
- [x] Auditoría con cadena HMAC verificable para eventos sellados.
- [x] Gateway de archivos fail-closed con interfaz antimalware y validaciones previas.
- [x] Motor no destructivo de retención, vista previa y legal hold.
- [x] Piloto técnico end-to-end automatizado con datos ficticios.
- [ ] Códigos de recuperación MFA/autoservicio, si se aprueban para el modelo de producto.
- [ ] Scanner antimalware real y almacenamiento privado de objetos desplegados.
- [ ] Carga/descarga privada HTTP de archivos habilitada y probada sobre esa infraestructura.
- [ ] Anclaje externo/almacenamiento inmutable de evidencia de auditoría.
- [ ] Monitoreo, métricas, alertas operacionales y gestión/rotación de secretos.
- [ ] Pruebas formales de accesibilidad, rendimiento y seguridad ofensiva antes de producción.
- [ ] Política de privacidad, retención/eliminación y tratamiento de datos aprobada; ejecución destructiva todavía bloqueada.
- [ ] Entorno privado desplegado con infraestructura y costos autorizados expresamente.
- [ ] Beta privada con datos ficticios aprobada antes de incorporar información real.
- [ ] Autorización expresa para procesar documentación real.

## Estado de seguridad de datos
No existen datos reales ni credenciales de producción incorporados intencionalmente al prototipo. El desarrollo continúa con información ficticia hasta completar los criterios pendientes.

## Bloque operativo implementado (beta ficticia)

Se agregan servicios, calendario persistente en la API, control de solapamientos/versiones, asistencia, revisión documental, requisitos por proyecto, evidencia por trabajador, tareas y cierre. Los roles planner/reviewer tienen alcances independientes; el planificador no accede a endpoints documentales. La nueva interfaz pública permite recorrer esos flujos con datos ficticios; `/app` sirve el cliente privado contra la API con sesión.

La migración `0009_operations` incorpora las tablas del bloque. El arranque privado exige el esquema esperado. Se incluyen métricas por proceso, exportación de checkpoint de auditoría y plantillas de despliegue/backup/restauración; no se presentan como infraestructura productiva desplegada. El adaptador SharePoint es de metadatos y sigue pendiente de identidad/runtime corporativa. Los pendientes de producción anteriores siguen vigentes.
