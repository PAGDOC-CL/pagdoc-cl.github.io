# PAGDOC — Gestión Documental Inteligente

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
