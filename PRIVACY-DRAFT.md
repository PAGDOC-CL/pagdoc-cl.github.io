# PAGDOC — Borrador de privacidad por diseño

**Estado: borrador técnico. No constituye asesoría jurídica ni una política publicada.** Debe revisarse antes de procesar información real.

## Objetivo

PAGDOC debe recopilar únicamente la información necesaria para gestionar acreditaciones, vigencias y documentación de empresas contratistas. La beta privada se probará primero con datos ficticios.

## Principios técnicos
- Minimización: no solicitar información que no sea necesaria para un requisito documental definido.
- Separación: cada empresa/tenant solo puede consultar sus propios recursos.
- Acceso mínimo: roles `admin`, `editor` y `viewer`; los permisos deben mantenerse en el servidor.
- Trazabilidad: altas, modificaciones, accesos sensibles y descargas deben generar auditoría.
- Seguridad: secretos fuera del repositorio; sesiones revocables; MFA; protección CSRF; cifrado de secretos sensibles.
- Privacidad por defecto: ningún documento se publica ni comparte mediante enlaces públicos.
- Datos ficticios primero: no habilitar documentos reales durante validaciones técnicas.

## Categorías previstas
Solo después de aprobación y configuración del cliente podrían existir:
- datos de empresa y proyectos;
- identificación laboral estrictamente necesaria de colaboradores;
- estado de requisitos y fechas de vigencia;
- antecedentes de vehículos/equipos necesarios para acreditación;
- archivos documentales aportados por usuarios autorizados;
- registros de auditoría y seguridad.

PAGDOC no debe diseñarse para almacenar contraseñas en texto plano, información de tarjetas de pago, credenciales de terceros ni secretos operacionales dentro de documentos de configuración.

## Controles de acceso
- Un usuario pertenece a un tenant.
- Toda consulta y modificación debe filtrar por tenant del usuario autenticado.
- Administradores gestionan usuarios y seguridad de su tenant.
- Editores gestionan contenido operativo.
- Viewers solo consultan.
- La desactivación de un usuario revoca sus sesiones activas.

## Archivos
Antes de habilitar archivos reales se requiere:
- almacenamiento privado, nunca dentro del repositorio GitHub público;
- identificadores aleatorios de objetos, sin nombres personales en rutas públicas;
- cifrado en tránsito y en reposo;
- límites de tamaño y tipos permitidos;
- validación de contenido y análisis antimalware;
- autorización en cada carga/descarga;
- auditoría de accesos y versiones;
- política de respaldo, retención y eliminación.

## Solicitudes y eliminación
La futura interfaz administrativa debe permitir localizar datos por empresa y sujeto, aplicar reglas de retención y registrar la eliminación cuando corresponda. Las copias de seguridad requieren una política compatible de expiración y restauración.

## Terceros y comunicaciones
No se enviarán correos, invitaciones o notificaciones a terceros desde PAGDOC sin habilitación expresa. Antes de integrar proveedores externos se debe documentar qué datos reciben, para qué finalidad y durante cuánto tiempo.

## Incidentes
Un procedimiento de producción deberá contemplar detección, contención, preservación de evidencia, rotación de secretos, revocación de sesiones, evaluación de alcance y comunicaciones que correspondan.

## Puerta de salida de beta
La documentación real solo debe habilitarse después de que infraestructura, almacenamiento, respaldos, controles de acceso, auditoría y requisitos de privacidad aplicables hayan sido revisados y aprobados expresamente.
