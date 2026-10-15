# PAGDOC — despliegue privado de beta

## Estado y alcance

El sitio público es una demostración con datos ficticios. `operacion.html` incluye un adaptador de demo local y un cliente de la API privada. Cuando FastAPI sirve `/app`, la interfaz usa sesión real y PostgreSQL, con CSRF y permisos comprobados en el servidor. No existe un backend privado alojado por este repositorio ni se ha contratado infraestructura.

El navegador público nunca recibe credenciales de Microsoft, claves de cifrado ni URLs temporales de descarga. SharePoint y las transferencias binarias siguen bloqueados hasta verificar identidad de aplicación, biblioteca de destino y controles de archivos. Instalar SharePoint en ChatGPT no configura la identidad de la aplicación PAGDOC.

## Preparación de infraestructura (sin contratación automática)

Para el piloto en un equipo Windows propio, sigue [WINDOWS-PRIVATE-SERVER.md](WINDOWS-PRIVATE-SERVER.md). Su composición local limita el puerto HTTPS al bucle local y genera secretos fuera de Git. La composición general de este documento está destinada a un host privado con dominio controlado.

1. Disponer de un equipo/servidor privado autorizado y un nombre HTTPS controlado por el propietario. Evaluar costo, respaldo y disponibilidad antes de usarlo.
2. Revisar `deployment/compose.yml`, `deployment/Dockerfile` y `deployment/Caddyfile`. Son plantillas: no se han ejecutado en un host productivo.
3. Configurar secretos fuera de Git: `PAGDOC_POSTGRES_PASSWORD`, `PAGDOC_DATABASE_URL`, `PAGDOC_SECRET_KEY`, `PAGDOC_ENCRYPTION_KEY`, `PAGDOC_PUBLIC_ORIGIN` y `PAGDOC_HOST`. La URL de base debe apuntar al servicio `database`, usar PostgreSQL y coincidir con usuario/contraseña configurados. La clave de aplicación debe ser aleatoria; no reutilizar valores de pruebas.
4. Desde `deployment/`, ejecutar `docker compose up --build -d` únicamente en ese host autorizado. PostgreSQL no expone puerto al exterior. El proxy termina HTTPS; la API corre con usuario sin privilegios y sistema de archivos de solo lectura.
5. Verificar `/ready` antes de habilitar el acceso. En staging/production el arranque exige la migración `0009_operations`; no crea tablas automáticamente.
6. Registrar el primer administrador de empresa desde el contenedor privado con `PAGDOC_ALLOW_ADMIN_PROVISIONING=YES python provision_admin.py`, o mediante `bash deployment/local/control.sh provision` en la instalación local. Exige migraciones, entorno privado, correo con formato válido y contraseña interactiva. No sobrescribe cuentas ni añade administradores a una empresa que ya tenga usuarios. Sus valores se guardan solo en la base privada. Esto no autoriza Microsoft 365 ni habilita archivos.
7. Abrir `/app`, iniciar sesión, configurar MFA y verificar el circuito con datos ficticios antes de incorporar documentación real. El aprovisionamiento ficticio anterior sigue disponible de forma separada mediante `provision_beta.py`.

La configuración HTTPS es necesaria: las cookies seguras no funcionan como autenticación privada sobre HTTP sin TLS.

## Permisos

- Administrador: gestión de usuarios, roles, revisión, planificación y cierre.
- Editor: registros documentales, servicios, planificación y sus pendientes.
- Revisor: lectura documental y decisiones de revisión; no modifica la planificación.
- Planificador: servicios, calendario y sus tareas. Los endpoints documentales quedan bloqueados, incluidos búsquedas y documentos históricos.
- Visor: lectura, sin escrituras.

Los cambios de rol/desactivación revocan sesiones. Una cuenta no puede cambiar su propio rol ni desactivarse a sí misma mediante la UI administrativa. La demo de roles no constituye autenticación ni representa controles del servidor.

## Datos y consistencia

Cada servicio, asignación, revisión, requisito de proyecto, evidencia y tarea se vincula a un tenant. La asignación es única por trabajador/día; PostgreSQL bloquea el trabajador al actualizar períodos y se comprueban versiones para detectar cambios simultáneos. Los reemplazos requieren motivo y quedan en historial. La asistencia registrada no se sobrescribe mediante planificación.

La aprobación se vincula a una huella de metadatos, requisito, trabajador y versión binaria. Cambiar esa información obliga a revisar nuevamente. La acreditación requiere evidencia registrada, aprobación y vigencia suficiente para el período. Sin requisitos configurados, archivos o asistencia, el cierre no se presenta como completo. Los requisitos de vehículos mantienen el cierre bloqueado hasta implementar una asociación inequívoca de cada vehículo al servicio.

## Monitoreo y respaldos

- `/health` y `/ready`: sondas sin contenido privado.
- `/ops/metrics`: métricas de solicitudes, errores y latencia del proceso actual; solo administrador. Falta recolector y alertas externos para operación real.
- Los logs de solicitud contienen método, ruta normalizada, estado y duración; no incluyen cuerpos, contraseñas, cookies ni tokens.
- `deployment/backup.sh`: exportación PostgreSQL cifrada con passphrase externa y suma SHA-256. Programar en un host autorizado y destino privado independiente; no guardar backups en Git.
- `deployment/restore-test.sh`: restauración exclusivamente a una base aislada cuyo nombre termina en `_restore_test`.
- Los scripts no programan tareas por sí solos y no se han probado en el host real. La CI comprueba backup/restauración PostgreSQL con datos ficticios.
- `/ops/audit-checkpoint` exporta el último sello para permitir anclaje externo. La respuesta indica expresamente que aún no está anclado. No equivale a WORM ni detecta por sí sola la eliminación del extremo final de la cadena.

## Puertas pendientes

Identidad Microsoft corporativa/runtime, biblioteca privada, antivirus real, transferencia binaria, integración de backups y monitoreo del host, anclaje externo de auditoría, revisión independiente de seguridad/accesibilidad/rendimiento y aprobación de privacidad/retención. No cargar documentación real hasta completar y autorizar esas condiciones.
