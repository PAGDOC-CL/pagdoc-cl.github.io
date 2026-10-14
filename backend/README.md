# PAGDOC — API privada (prototipo técnico)

**No desplegar en producción ni cargar datos reales todavía.** Este backend permanece separado del sitio público de GitHub Pages. La landing y la demostración estática no ejecutan esta API ni almacenan documentación privada.

## Entrada del servidor privado
La aplicación ensamblada se expone desde `server.py` y valida la configuración antes de registrar módulos privados:

```bash
uvicorn server:app --reload
```

`server.py` instala primero la auditoría sellada y después registra historial documental, requisitos, alertas internas, búsqueda, retención, readiness y hardening HTTP.

## Funcionalidad incorporada
- Arquitectura multiempresa con separación lógica por tenant.
- Roles `admin`, `editor` y `viewer`.
- Gestión de usuarios, proyectos, trabajadores, vehículos y documentos.
- Dashboard documental y semáforo por vigencia.
- Búsqueda paginada por texto, estado, tipo y proyecto.
- Argon2 para contraseñas y sesiones opacas almacenadas del lado servidor.
- Revocación individual/global de sesiones y revocación al desactivar usuarios.
- Cookies `HttpOnly`, `Secure`, `SameSite=Strict`, CSRF y límite de intentos de login.
- MFA TOTP y recuperación administrativa de acceso.
- Requisitos documentales configurables, vigencias y alertas internas opt-in.
- Historial de cambios de metadatos documentales.
- Auditoría por tenant con sellos HMAC encadenados para eventos nuevos y endpoint administrativo de verificación.
- Motor de retención **no destructivo** con reglas por tipo documental, vista previa y legal hold.
- Readiness probe que exige PostgreSQL y revisión Alembic exacta en staging/producción.
- CSP restrictiva y HSTS para entornos staging/production, además de las cabeceras defensivas del núcleo.
- PostgreSQL mediante `psycopg` y migraciones Alembic.

## Archivos privados: estado real
Existe una capa de servicio para archivos, pero los endpoints binarios HTTP siguen deliberadamente deshabilitados.

La implementación actual incorpora:
- validación de tamaño y firma/tipo para PDF, JPEG y PNG;
- cifrado local de prototipo con Fernet;
- aislamiento físico por tenant dentro del store local de pruebas;
- registro de versiones binarias con `object_key`, tamaño, SHA-256, tipo, scanner y creador;
- verificación de integridad SHA-256 antes de devolver bytes desde la capa de servicio;
- gateway de ingreso fail-closed: si el scanner falla o rechaza el archivo, no se almacena;
- limpieza del objeto si falla el registro transaccional de la versión.

**Esto no equivale a almacenamiento de producción.** Antes de habilitar carga/descarga HTTP deben existir un scanner antimalware real y un objeto privado de almacenamiento autorizado. No hay un scanner ficticio conectado al servidor real ni se permite saltarse ese control.

## Retención y privacidad
`retention_api.py` permite configurar ventanas posteriores al vencimiento, consultar candidatos y aplicar/revocar legal holds. El endpoint de vista previa responde explícitamente con `destructive_actions_enabled: false`.

No hay endpoint que elimine documentos por retención. La eliminación destructiva permanece bloqueada hasta aprobar la política de privacidad/retención, respaldo, trazabilidad y procedimiento operacional.

## Auditoría: alcance y límite
Los nuevos eventos sensibles pueden quedar sellados mediante una cadena HMAC por tenant. La verificación detecta modificaciones, huecos o inserciones no selladas dentro del tramo controlado.

No se debe describir esta función como WORM o inmutabilidad absoluta: para demostrar la eliminación del último extremo de una cadena hace falta un anclaje externo/servicio de logging independiente, todavía pendiente.

## Esquema y migraciones
El esquema está versionado hasta:

```text
0001_initial
0002_user_mfa
0003_requirements
0004_document_revisions
0005_alert_inbox
0006_document_file_versions
0007_audit_seals
0008_retention_policy
```

La CI ejecuta `alembic upgrade head` desde una base limpia tanto en SQLite como en PostgreSQL 17.

## Estado de pruebas verificado
El workflow `.github/workflows/backend-tests.yml` usa Python 3.12 y PostgreSQL 17. La última ejecución verificada completó correctamente:

- **121 pruebas** en la suite principal del backend;
- **1 prueba** end-to-end del servidor privado ensamblado con datos ficticios;
- **2 pruebas** de concurrencia real sobre PostgreSQL;
- **124 pruebas aprobadas en total**;
- migraciones `0001` a `0008` aplicadas correctamente en SQLite y PostgreSQL;
- backup y restauración PostgreSQL verificados;
- guard del repositorio público aprobado.

La suite cubre autenticación, MFA, sesiones, rate limiting, CSRF, roles, aislamiento por tenant, requisitos, alertas, historial, búsqueda, retención, almacenamiento cifrado de prototipo, gateway fail-closed, integridad de auditoría, readiness, cabeceras HTTP y concurrencia.

## Configuración segura de entorno
`.env.example` contiene únicamente placeholders. Nunca se debe subir un `.env` real.

El arranque mediante `server.py` falla de forma cerrada si la configuración es insegura. En staging/producción se requiere:
- PostgreSQL;
- `PAGDOC_SECRET_KEY` suficientemente largo;
- clave Fernet válida;
- `PAGDOC_PUBLIC_ORIGIN` HTTPS.

## Aprovisionamiento local ficticio
`bootstrap_demo.py` solo funciona si se define `PAGDOC_ALLOW_DEMO_BOOTSTRAP=YES`, la base es SQLite y el correo termina en `@example.invalid`. No envía mensajes y no debe utilizarse con información real.

## Controles pendientes antes de producción
- scanner antimalware real y almacenamiento privado de objetos;
- endpoints privados de carga/descarga sobre esa infraestructura;
- gestión/rotación segura de secretos y llaves en infraestructura autorizada;
- monitoreo, métricas y alertas operacionales;
- anclaje externo/inmutable de evidencia de auditoría;
- pruebas formales de accesibilidad, rendimiento y seguridad ofensiva controlada;
- aprobación formal de privacidad, retención y eliminación;
- despliegue privado con infraestructura y costos expresamente autorizados;
- autorización explícita antes de procesar documentación real.

No se incluyen cuentas, credenciales ni información real de MUFAS CHILE, trabajadores o clientes.
