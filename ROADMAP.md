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

## Criterios para declarar PAGDOC 100 % operativo

Cada criterio debe demostrarse con pruebas, no solo con código:
- [ ] Sitio comercial y demo accesibles en HTTPS.
- [ ] CI de backend en verde, con pruebas de autorización y aislamiento multiempresa.
- [ ] Inicio de sesión seguro, MFA, cierre de sesión revocable y recuperación de acceso.
- [ ] Alta, baja y edición de empresas, usuarios y permisos, con trazabilidad.
- [ ] Gestión de proyectos, trabajadores, vehículos y documentación, con búsquedas y filtros.
- [ ] Carga, descarga y versionado de archivos privados, con controles de tamaño, tipo y malware.
- [ ] Reglas de vigencia por tipo documental, alertas y reportes exportables.
- [ ] Registro de auditoría íntegro y trazabilidad de modificaciones.
- [ ] PostgreSQL con migraciones y copias de seguridad restauradas en prueba.
- [ ] Pruebas de aislamiento de empresas, accesibilidad, rendimiento y seguridad.
- [ ] Políticas de privacidad y retención de documentos aprobadas.
- [ ] Entorno privado desplegado con dominio y costos autorizados expresamente.
- [ ] Piloto con datos ficticios validado de extremo a extremo.
- [ ] Autorización expresa antes de procesar documentación real.

### Registro de avances del 13 de octubre de 2026
- Se incorporó `bootstrap_demo.py` para aprovisionamiento local restringido.
- Se incorporó CI de pruebas automáticas en GitHub Actions.
- Se amplió `test_app.py` a 14 pruebas de autenticación, autorización, auditoría y aislamiento.
- Se reforzó la validación de entradas en `app.py`.
- El estado de CI y la publicación de backend siguen pendientes de verificación.
