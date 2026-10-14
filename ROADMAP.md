# PAGDOC | Plan de desarrollo y criterios de avance

Actualización: 13 de octubre de 2026.

## Entregado y verificado
- Landing page pública: `index.html`.
- Panel público demostrativo multi-módulo con datos 100 % ficticios: `demo.html`.
- GitHub Pages desplegado correctamente por CI.
- API multiempresa de prototipo privada y **no desplegada**: `backend/app.py`.
- Modelos y endpoints para usuarios, proyectos, trabajadores, vehículos, documentos, dashboard y auditoría.
- Roles `admin`, `editor` y `viewer` con autorización por operación.
- Separación lógica por empresa/tenant en consultas y modificaciones.
- Autenticación con hash Argon2 y sesiones opacas almacenadas del lado servidor.
- Revocación de sesión individual, cierre de todas las sesiones y revocación al desactivar un usuario.
- Cookies `Secure`/`HttpOnly`/`SameSite=Strict` y protección CSRF para operaciones de escritura.
- Límite de intentos fallidos de inicio de sesión por correo + origen anonimizado.
- Cabeceras defensivas (`nosniff`, `DENY`, `no-referrer`, `no-store` y Permissions Policy).
- Alta local restringida de empresa y administrador ficticios: `backend/bootstrap_demo.py`.
- Soporte de conexión PostgreSQL mediante `psycopg` y esquema versionado con Alembic.
- Migración inicial `0001_initial` validada automáticamente en CI sobre una base limpia.
- Automatización de pruebas en `.github/workflows/backend-tests.yml`.
- **CI confirmado en verde: 30 pruebas aprobadas** de autenticación, sesiones, rate limiting, CSRF, autorización, aislamiento multiempresa, auditoría y módulos centrales.

## Siguiente bloque técnico antes de producción
1. Ejecutar migraciones también contra una instancia PostgreSQL real de ensayo y validar concurrencia/transacciones.
2. Implementar MFA y recuperación segura de acceso.
3. Diseñar almacenamiento privado de archivos con autorización, cifrado, límites, validación de tipo y análisis antimalware.
4. Añadir historial/versionado documental, reglas configurables de vigencia y notificaciones opt-in.
5. Implementar copias de seguridad y ejecutar una restauración de prueba.
6. Ampliar pruebas de accesibilidad, rendimiento, concurrencia y seguridad ofensiva controlada.
7. Completar políticas de privacidad, retención y eliminación de datos.
8. Desplegar beta privada exclusivamente con datos ficticios después de validar infraestructura y costos.
9. Habilitar información real solo tras autorización expresa y validación de seguridad/privacidad.

## Reglas permanentes del proyecto
- Costo inicial aprobado: **$0 CLP**. No contratar recursos ni generar cobros sin aprobación explícita.
- Nunca subir datos reales de trabajadores, clientes o MUFAS CHILE al repositorio público.
- La demo pública no autentica usuarios ni almacena documentación.
- El backend no está desplegado ni habilitado para producción.
- No enviar correos, invitaciones ni mensajes a terceros sin autorización del propietario.
- No publicar secretos, contraseñas, tokens, archivos `.env`, bases de datos ni documentos privados.

## Criterios para declarar PAGDOC 100 % operativo

Cada criterio debe demostrarse con una prueba o evidencia técnica; escribir código por sí solo no lo completa.

- [x] Sitio comercial publicado mediante HTTPS en GitHub Pages.
- [x] Demo pública multi-módulo con datos ficticios y exportación CSV.
- [x] CI de backend en verde con pruebas de autorización y aislamiento multiempresa.
- [x] Base de gestión de usuarios, roles, proyectos, trabajadores, vehículos, documentos y auditoría.
- [x] Protección CSRF y cookies seguras en el prototipo de autenticación.
- [x] Sesiones revocables del lado servidor y límite de intentos de inicio de sesión.
- [x] Migraciones versionadas con Alembic y driver PostgreSQL incorporado; migración validada en CI sobre SQLite limpia.
- [ ] MFA y recuperación de acceso.
- [ ] Migraciones y operación probadas contra PostgreSQL real de ensayo.
- [ ] Carga, descarga y versionado de archivos privados con cifrado, límites y análisis antimalware.
- [ ] Reglas configurables de requisitos/vigencias y motor de alertas.
- [ ] Copias de seguridad con restauración validada.
- [ ] Auditoría ampliada e íntegra para cambios sensibles y accesos a documentos.
- [ ] Pruebas de accesibilidad, rendimiento, concurrencia y revisión de seguridad antes de producción.
- [ ] Política de privacidad, retención/eliminación y tratamiento de datos aprobada.
- [ ] Entorno privado desplegado con infraestructura y costos autorizados expresamente.
- [ ] Piloto de extremo a extremo con datos ficticios aprobado antes de incorporar información real.
- [ ] Autorización expresa antes de procesar documentación real.

## Evidencia de la etapa actual
- GitHub Actions de backend: **success**.
- Suite: **30 passed**.
- Migración Alembic inicial: **upgrade head exitoso** en CI.
- GitHub Pages del panel demostrativo: despliegue exitoso.
- No existen datos reales ni credenciales de producción incorporados intencionalmente al prototipo.
