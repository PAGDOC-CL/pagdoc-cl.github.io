# PAGDOC — API privada (prototipo técnico)

**No desplegar en producción ni cargar datos reales.** Este backend permanece aislado del sitio público de GitHub Pages. GitHub Pages solo aloja la landing y la demostración estática; no ejecuta esta API, bases de datos ni autenticación privada.

## Funcionalidad incorporada
- Arquitectura multiempresa (tenant) con separación lógica de consultas y modificaciones.
- Roles `admin`, `editor` y `viewer`.
- Usuarios: listado, alta y activación/desactivación por administradores.
- Proyectos, trabajadores y vehículos: alta, consulta y activación/desactivación.
- Documentos: alta, consulta, asociación opcional a proyecto y semáforo por vigencia.
- Dashboard: total documental, estados y entidades activas.
- Auditoría por tenant con usuario, acción, tipo de recurso, identificador y fecha.
- Autenticación con hash Argon2.
- Sesiones opacas almacenadas del lado servidor, con vencimiento y revocación.
- Cierre de sesión individual, cierre de todas las sesiones y revocación al desactivar usuarios.
- Cookies `HttpOnly`, `Secure`, `SameSite=Strict` y protección CSRF de doble token validada contra la sesión.
- Limitación de intentos fallidos de login por correo y origen anonimizado.
- Cabeceras defensivas, incluida `Permissions-Policy`.
- Validación de entradas mediante Pydantic.
- Soporte de URL PostgreSQL mediante `psycopg`.
- Esquema versionado con Alembic en `migrations/`.
- API sin carga de archivos: el almacenamiento documental real se mantiene bloqueado hasta completar su diseño seguro.

## Estado de pruebas

GitHub Actions ejecuta el workflow `.github/workflows/backend-tests.yml` con Python 3.12. La CI también crea una base limpia y ejecuta `alembic upgrade head` antes de la suite.

**Resultado verificado de la etapa actual: 30 pruebas aprobadas y migración inicial aplicada correctamente.** La suite cubre autenticación, sesiones revocables, límite de intentos, cookies, CSRF, aislamiento entre empresas, roles, usuarios, proyectos, trabajadores, vehículos, documentos, dashboard, auditoría y prohibición de modificar recursos de otro tenant.

## Ejecutar localmente (solo pruebas con datos ficticios)
1. Instalar Python 3.11+ y crear un entorno virtual.
2. `pip install -r requirements.txt`
3. Definir `PAGDOC_SECRET_KEY` con un valor aleatorio de al menos 32 caracteres.
4. Copiar `.env.example` como referencia de variables, sin subir el `.env` real.
5. Para crear el esquema versionado: `python -m alembic upgrade head`.
6. Ejecutar `uvicorn app:app --reload` desde la carpeta `backend`.

No se incluyen cuentas, credenciales ni información real.

## PostgreSQL

El código incorpora el driver `psycopg` y Alembic acepta `PAGDOC_DATABASE_URL`. Esto prepara el proyecto para PostgreSQL, pero **aún no se ha validado contra una instancia PostgreSQL real**. Esa comprobación debe completarse antes de una beta privada.

## Aprovisionamiento local de demostración

`bootstrap_demo.py` crea una empresa ficticia y un administrador de prueba. Se bloquea salvo que `PAGDOC_ALLOW_DEMO_BOOTSTRAP=YES` esté definido y que la base configurada sea SQLite. Solo admite correos terminados en `@example.invalid`, solicita la contraseña mediante entrada oculta y no envía mensajes.

No debe utilizarse con MUFAS CHILE, trabajadores reales, clientes reales ni infraestructura pública.

## Controles aún obligatorios antes de producción
- MFA y recuperación segura de acceso.
- Validación real de PostgreSQL y pruebas de concurrencia/transacciones.
- Almacenamiento privado de archivos con autorización, cifrado, límites, validación de tipo y análisis antimalware.
- Historial/versionado documental y trazabilidad completa de accesos/descargas.
- Copias de seguridad con restauración probada.
- Monitoreo, alertas operacionales y gestión de secretos.
- Pruebas de accesibilidad, rendimiento, concurrencia y seguridad.
- Revisión de privacidad, retención y eliminación de datos.
- Infraestructura y dominio con cualquier costo aprobado expresamente por el propietario.

**La landing y la demo pública no deben conectarse a esta API ni procesar documentos reales hasta completar estos controles.**
