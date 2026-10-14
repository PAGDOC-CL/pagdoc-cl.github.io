# PAGDOC | Plan de desarrollo y criterios de avance

Actualización: 13 de octubre de 2026.

## Entregado en repositorio
- Landing page pública: `index.html`.
- Panel público demostrativo con datos ficticios: `demo.html`.
- API de prototipo privada (sin despliegue): `backend/app.py`.
- Pruebas de acceso, separación de empresas, validación y auditoría: `backend/test_app.py`.
- Automatización de pruebas en GitHub Actions: `.github/workflows/backend-tests.yml`.
- Alta local de empresa y usuario de prueba: `backend/bootstrap_demo.py`.

## Próximas etapas, por orden
1. Confirmar resultados de CI y corregir cualquier prueba fallida.
2. Reemplazar SQLite por PostgreSQL con migraciones controladas.
3. Incorporar protección CSRF, bloqueo de intentos, sesiones revocables y MFA.
4. Implementar administración de usuarios, permisos y recuperación de acceso.
5. Diseñar repositorio privado de documentos con cifrado, límites, validación de archivos y antivirus.
6. Incorporar historial de versiones, auditoría completa y notificaciones opt-in.
7. Realizar pruebas de aislamiento entre empresas, restauración de backups y revisión de privacidad.
8. Desplegar una beta privada sin datos reales, solo después de validar seguridad y costos.
9. Habilitar datos reales únicamente con autorización y garantías de tratamiento de datos.

## Reglas del proyecto
- Costo inicial aprobado: $0 CLP. No contratar recursos sin aprobación explícita.
- Nunca subir datos reales de trabajadores, clientes o MUFAS CHILE al repositorio público.
- La demo pública no autentica usuarios ni almacena documentación.
- El backend no está desplegado ni habilitado para producción.
- No se enviarán correos ni invitaciones sin autorización del propietario.
