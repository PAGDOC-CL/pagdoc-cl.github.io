# PAGDOC — API privada (prototipo técnico)

**No desplegar en producción ni cargar datos reales.** Este backend permanece aislado del sitio público de GitHub Pages. GitHub Pages solo aloja la landing y la demostración estática; no ejecuta esta API, bases de datos ni autenticación privada.

## Funcionalidad incorporada
- Arquitectura multiempresa (tenant) con separación lógica de consultas y modificaciones.
- Roles `admin`, `editor` y `viewer`.
- Usuarios: listado, alta y activación/desactivación por administradores.
- Proyectos, trabajadores y vehículos: alta, consulta y activación/desactivación.
- Documentos: alta, consulta, asociación opcional a proyecto y semáforo por vigencia.
- Dashboard: total documental, estados y entidades activas.
- Auditoría inicial por tenant con usuario, acción, tipo de recurso, identificador y fecha.
- Autenticación con hash Argon2 y cookie firmada `HttpOnly`, `Secure`, `SameSite=Strict`.
- Protección CSRF de doble token para operaciones de escritura y cierre de sesión.
- Cabeceras defensivas: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y `Cache-Control`.
- Validación de entradas mediante Pydantic.
- API sin carga de archivos: el almacenamiento documental real se mantiene bloqueado hasta completar su diseño seguro.

## Estado de pruebas

GitHub Actions ejecuta el workflow `.github/workflows/backend-tests.yml` con Python 3.12.

**Resultado verificado de la etapa actual: 26 pruebas aprobadas.** La suite cubre autenticación, cookies, CSRF, aislamiento entre empresas, roles, usuarios, proyectos, trabajadores, vehículos, documentos, dashboard, auditoría y prohibición de modificar recursos de otro tenant.

## Ejecutar localmente (solo pruebas con datos ficticios)
1. Instalar Python 3.11+ y crear un entorno virtual.
2. `pip install -r requirements.txt`
3. Definir `PAGDOC_SECRET_KEY` con un valor aleatorio de al menos 32 caracteres.
4. Opcionalmente definir `PAGDOC_DATABASE_URL`; por defecto se usa SQLite local.
5. Ejecutar `uvicorn app:app --reload` desde la carpeta `backend`.

No se incluyen cuentas, credenciales ni información real.

## Aprovisionamiento local de demostración

`bootstrap_demo.py` crea una empresa ficticia y un administrador de prueba. Se bloquea salvo que `PAGDOC_ALLOW_DEMO_BOOTSTRAP=YES` esté definido y que la base configurada sea SQLite. Solo admite correos terminados en `@example.invalid`, solicita la contraseña mediante entrada oculta y no envía mensajes.

No debe utilizarse con MUFAS CHILE, trabajadores reales, clientes reales ni infraestructura pública.

## Controles aún obligatorios antes de producción
- PostgreSQL y migraciones versionadas.
- Sesiones revocables del lado servidor.
- Control de intentos de inicio de sesión y bloqueo/rate limiting.
- MFA y recuperación segura de acceso.
- Invitación y alta de usuarios con verificación.
- Almacenamiento privado de archivos con autorización, cifrado, límites, validación de tipo y análisis antimalware.
- Historial/versionado documental y trazabilidad completa de accesos/descargas.
- Copias de seguridad con restauración probada.
- Monitoreo, alertas operacionales y gestión de secretos.
- Pruebas de accesibilidad, rendimiento, concurrencia y seguridad.
- Revisión de privacidad, retención y eliminación de datos.
- Infraestructura y dominio con cualquier costo aprobado expresamente por el propietario.

**La landing y la demo pública no deben conectarse a esta API ni procesar documentos reales hasta completar estos controles.**
