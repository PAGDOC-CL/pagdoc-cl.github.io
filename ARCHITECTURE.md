# PAGDOC — Arquitectura objetivo

## Separación de entornos

### 1. Sitio público
GitHub Pages sirve únicamente la landing y la demostración ficticia. No contiene autenticación privada, documentos de clientes, base de datos ni secretos.

### 2. Aplicación privada
El backend FastAPI se desplegará en infraestructura separada cuando exista autorización para ello. La aplicación privada deberá usar HTTPS, PostgreSQL, almacenamiento de objetos privado y un administrador de secretos.

### 3. Datos
La unidad de aislamiento es el `tenant`. Usuarios, proyectos, trabajadores, vehículos, documentos, sesiones y auditoría deben estar asociados al tenant y toda operación debe autorizarse en el servidor.

## Flujo de autenticación
1. Usuario entrega correo y contraseña por HTTPS.
2. Se verifica hash Argon2.
3. Si MFA está habilitado, se valida TOTP.
4. El servidor crea una sesión opaca aleatoria y almacena únicamente su hash.
5. El navegador recibe cookie `Secure`, `HttpOnly`, `SameSite=Strict` y token CSRF separado.
6. Escrituras exigen sesión, rol y validación CSRF.
7. Logout, logout-all, cambio de contraseña o desactivación revocan sesiones del lado servidor.

## Flujo documental objetivo
1. Usuario autorizado selecciona sujeto, requisito y proyecto.
2. API valida tenant, permiso, tamaño y metadatos.
3. Servicio de archivos valida firma real del archivo y tipo permitido.
4. Un análisis antimalware debe aprobar el objeto antes de marcarlo disponible.
5. El archivo se guarda cifrado en almacenamiento privado con identificador aleatorio; el nombre original solo es metadato.
6. Base de datos almacena metadatos, hash, versión, fechas y referencia al objeto.
7. Cada descarga vuelve a validar usuario, tenant y permiso y registra auditoría.

El prototipo actual ya incluye un componente de almacenamiento local cifrado para pruebas, pero no está conectado a endpoints porque todavía no existe el análisis antimalware ni el almacenamiento privado de producción.

## Base de datos
- Desarrollo local: SQLite solo para rapidez de pruebas.
- Objetivo privado: PostgreSQL.
- Migraciones: Alembic versionado.
- CI: migraciones se validan sobre SQLite y PostgreSQL temporal.
- Respaldos: `pg_dump`/`pg_restore` se validan sobre PostgreSQL temporal en CI; producción requerirá copias programadas, cifradas y con retención definida.

## Auditoría
La auditoría registra tenant, usuario, acción, tipo de recurso, identificador y fecha. Producción debe ampliar esto a accesos/descargas de documentos, cambios de permisos, operaciones administrativas y eventos de seguridad, evitando almacenar contenido sensible dentro del log.

## Comunicaciones
Las alertas por correo u otros canales estarán deshabilitadas hasta autorización expresa. El motor de alertas deberá generar primero eventos internos; un proveedor de mensajería será una integración separada y opt-in.

## Controles que impiden una publicación prematura
- backend no desplegado públicamente;
- carga de archivos no expuesta por API;
- datos reales prohibidos en GitHub y CI;
- variables secretas fuera del repositorio;
- demo pública explícitamente identificada como ficticia;
- CI falla ante artefactos privados comunes o formatos de secretos conocidos.
