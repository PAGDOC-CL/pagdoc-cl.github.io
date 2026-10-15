# PAGDOC — Gestión Documental Inteligente

Servidor privado en un equipo Windows propio: [instalación local con WSL y registro del administrador de empresa](WINDOWS-PRIVATE-SERVER.md). Requiere verificación en el equipo final y mantiene la carga de documentos reales deshabilitada hasta integrar los controles pendientes.

PAGDOC es un proyecto de control documental para empresas contratistas: vigencias, acreditación, trabajadores, vehículos, proyectos y trazabilidad.

## Estado actual

- Sitio comercial: publicado en GitHub Pages.
- Demo pública: panel multi-módulo con datos 100 % ficticios.
- Backend: código de prototipo técnico en desarrollo, **no desplegado para producción**.
- Datos reales: **no autorizados** en este repositorio ni en la demo.
- Presupuesto inicial autorizado: **$0 CLP**; no se contratan servicios desde este proyecto sin aprobación expresa.

## Accesos públicos

- Sitio: https://pagdoc-cl.github.io/
- Vista de usuario: https://pagdoc-cl.github.io/usuario.html
- Demo: https://pagdoc-cl.github.io/demo.html
- Planificador: https://pagdoc-cl.github.io/demo.html#planificador

## Capacidades desarrolladas

### Demo
- Dashboard ejecutivo.
- Semáforo de vencimientos.
- Documentos, trabajadores, vehículos y proyectos.
- Búsqueda y filtros.
- Auditoría ficticia.
- Exportación CSV.
- Planificador de personal con calendario mensual, descanso, terreno y asignación de servicio por período.
- La planificación ficticia se conserva únicamente en el navegador; no se sincroniza entre usuarios.

### Backend de prototipo
- FastAPI + SQLAlchemy.
- Multiempresa/tenant.
- Roles admin, editor y viewer.
- Proyectos, trabajadores, vehículos, documentos, usuarios y auditoría.
- Argon2 para contraseñas.
- Sesiones opacas revocables del lado servidor.
- CSRF y cookies seguras.
- Límite de intentos de inicio de sesión.
- MFA TOTP con secreto cifrado.
- Restablecimiento administrativo de contraseña/MFA con revocación de sesiones.
- Alembic y soporte PostgreSQL.
- Prototipo de almacenamiento local cifrado y validación estricta de PDF/JPEG/PNG, todavía sin exposición por API.
- CI automatizada con pruebas de seguridad, aislamiento y migraciones.
- Guardia del repositorio público contra artefactos privados y patrones comunes de secretos.

## Límites deliberados

PAGDOC todavía no debe recibir documentación real. Antes de producción faltan, entre otros puntos, almacenamiento privado de objetos con análisis antimalware, monitoreo, políticas aprobadas de privacidad/retención, infraestructura privada, revisión de seguridad y piloto integral con datos ficticios.

## Documentación

- `ROADMAP.md`: criterios verificables de avance.
- `ARCHITECTURE.md`: arquitectura objetivo y separación público/privado.
- `SECURITY.md`: límites de seguridad del repositorio.
- `PRIVACY-DRAFT.md`: borrador de privacidad por diseño.
- `DATA-RETENTION-DRAFT.md`: borrador de retención/eliminación.
- `OPERATIONS.md`: runbook de respaldo, restauración e incidentes.
- `backend/README.md`: detalle técnico del backend.

## Regla de desarrollo

Una funcionalidad no se considera terminada solo porque exista código: debe contar con prueba o evidencia técnica correspondiente. No se publicará como “producción” mientras existan controles críticos pendientes.

## Centro operativo y aplicación privada

- Demo operativa: https://pagdoc-cl.github.io/operacion.html
- Servicios con cliente, proyecto, ubicación, supervisor y período.
- Calendario por colaborador/equipo, conflictos entre servicios/descansos y asistencia realizada.
- Bandeja documental con estados, motivos, historial y revisión por rol.
- Pendientes con responsable, plazo, estado y control de cambios simultáneos.
- Checklist de cierre con requisitos, evidencia, asistencia y tareas.
- Gestión de usuarios/roles, revocación de sesiones y configuración MFA en privado.
- Cliente privado servido en `/app` por FastAPI, con sesión real y permisos en servidor. No se publica la API en GitHub Pages.

La demo guarda solo datos ficticios en el navegador. La API privada está implementada y probada; su alojamiento externo, SharePoint runtime y transferencia de archivos aún no están habilitados. Consultar `PRIVATE-DEPLOYMENT.md` y `SHAREPOINT-INTEGRATION.md` para límites y pasos pendientes. No se han contratado servicios.
