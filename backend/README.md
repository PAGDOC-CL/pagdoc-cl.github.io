# PAGDOC — API privada (prototipo técnico)

**No desplegar en producción ni cargar datos reales.** Este backend es una base técnica aislada del sitio público de GitHub Pages. GitHub Pages aloja HTML estático y no ejecuta Python, bases de datos ni autenticación.

## Funcionalidad incorporada
- Usuarios vinculados a una empresa (tenant) y roles admin/editor/viewer.
- Autenticación con hash Argon2, cookie firmada HttpOnly/Secure/SameSite Strict de 1 hora.
- Proyectos y documentos siempre consultados por tenant.
- Semáforo documental calculado según fecha.
- Bitácora inicial de creación de proyectos y documentos.
- API con validación de entrada; no permite carga de archivos.

## Ejecutar localmente (solo pruebas)
1. Instalar Python 3.11+ y crear entorno virtual.
2. `pip install -r requirements.txt`
3. Configurar `PAGDOC_SECRET_KEY` con un valor aleatorio de al menos 32 caracteres.
4. `uvicorn app:app --reload` desde la carpeta `backend`.

La base SQLite se crea localmente al iniciar. No se incluyen cuentas, credenciales ni datos reales. Para crear cuentas de prueba se necesita un procedimiento local de aprovisionamiento seguro, aún pendiente.

## Bloqueos antes de un despliegue real
- PostgreSQL gestionado y migraciones versionadas; política de respaldos/restauración.
- Aprovisionamiento seguro de usuarios, recuperación de contraseña y MFA.
- Protección anti fuerza bruta, CSRF, revocación de sesiones, CORS y HTTPS detrás de proxy confiable.
- Pruebas automatizadas de aislamiento entre tenants y controles de autorización.
- Almacenamiento privado de archivos, antivirus, cifrado, cuotas y descargas autorizadas.
- Registro de auditoría completo e inmutable, monitoreo y alertas.
- Gestión de secretos, seguridad de dependencias, pruebas de penetración y revisión de privacidad.
- Infraestructura y dominio con costos aprobados expresamente por el propietario.

**La landing page y demo pública no deben conectarse a esta API antes de completar los controles.**
