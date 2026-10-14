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
- Autenticación con hash Argon2, cookies `Secure`/`HttpOnly`/`SameSite=Strict` y protección CSRF para operaciones de escritura.
- Cabeceras defensivas básicas (`nosniff`, `DENY`, `no-referrer`, `no-store`).
- Alta local restringida de empresa y administrador ficticios: `backend/bootstrap_demo.py`.
- Automatización de pruebas en `.github/workflows/backend-tests.yml`.
- **CI confirmado en verde: 26 pruebas aprobadas** de autenticación, autorización, CSRF, aislamiento multiempresa, auditoría y módulos centrales.

## Siguiente bloque técnico antes de producción
1. Migrar de SQLite de desarrollo a PostgreSQL y añadir migraciones versionadas.
2. Implementar sesiones revocables del lado servidor, control de intentos de acceso y MFA.
3. Implementar recuperación de acceso e invitación de usuarios sin revelar credenciales.
4. Diseñar almacenamiento privado de archivos con autorización, cifrado, límites, validación de tipo y análisis antimalware.
5. Añadir historial/versionado documental, reglas configurables de vigencia y notificaciones opt-in.
6. Implementar copias de seguridad y ejecutar una restauración de prueba.
7. Ampliar pruebas de accesibilidad, rendimiento, concurrencia y seguridad ofensiva controlada.
8. Completar políticas de privacidad, retención y eliminación de datos.
9. Desplegar beta privada exclusivamente con datos ficticios después de validar infraestructura y costos.
10. Habilitar información real solo tras autorización expresa y validación de seguridad/privacidad.

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
- [ ] MFA, recuperación de acceso, control de intentos y sesiones revocables del lado servidor.
- [ ] PostgreSQL con migraciones versionadas.
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
- Ejecución de GitHub Actions `PAGDOC backend tests`: **26 passed**.
- Ejecución de GitHub Pages para el nuevo panel demostrativo: **success**.
- No existen datos reales ni credenciales de producción incorporados intencionalmente al prototipo.
