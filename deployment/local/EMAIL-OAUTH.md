# Microsoft 365 SMTP OAuth — servidor privado

Este modo conserva MFA/Authenticator. La aplicación de Entra debe ser de un solo
inquilino, permitir clientes públicos y solicitar SMTP.Send delegado. El permiso
aparece bajo Microsoft Graph en el portal, pero el token se solicita para el
recurso `https://outlook.office.com/SMTP.Send`. No requiere secreto de cliente.
La política del inquilino puede exigir consentimiento administrativo o bloquear
el flujo por código de dispositivo. SMTP AUTH debe estar permitido para el buzón.
No deshabilitar MFA ni las protecciones de la organización para resolver errores.

## Instalación

1. Respaldar el servidor siguiendo el procedimiento privado habitual. Conservar
   cualquier cambio local de Caddy. Esta actualización no modifica Caddyfile.
2. Instalar el código revisado en el repositorio local. No usar `reset --hard`,
   `clean` ni un comando que publique runtime.env o el almacenamiento privado.
3. Ejecutar `bash deployment/local/control.sh start` para reconstruir el API.
   Los avisos continúan deshabilitados si aún no había configuración de correo.
4. Ejecutar:

   ```bash
   bash deployment/local/control.sh configure-email-oauth \
     --tenant ID_DIRECTORIO --client ID_APLICACION --username CORREO_REMITENTE
   ```

   Reemplazar los tres valores por los de la organización. El asistente muestra
   una dirección de Microsoft y un código temporal. Autorizar desde un navegador,
   revisando aplicación, cuenta y permiso solicitado. No compartir el código,
   credenciales ni tokens. Si pide administrador, conservar el error y solicitar
   su intervención. Cancelar con Ctrl+C si es necesario.
5. La prueba inicial solo autentica SMTP sobre STARTTLS con certificados
   verificados: no envía mensajes. Si falla no activa la entrega. En caso de éxito
   cifra los tokens con la clave privada de PAGDOC en el volumen de archivos;
   directorio 700, archivo 600, bloqueo entre API y worker, rotación atómica.
   Los IDs y tokens no se incorporan al repositorio.
6. Tras éxito, ejecutar `bash deployment/local/control.sh start` otra vez. Se
   activa el worker de notificaciones. Cada destinatario debe haber habilitado
   sus avisos; se mantienen alcance por rol y prevención de duplicados diarios.
7. Comprobar en Mi seguridad que la entrega está configurada. Probar recuperación
   con la propia cuenta y confirmar recepción antes de anunciar servicio activo.
   Si existe remote.env válido, los enlaces de recuperación usan su IP NetBird.
   El destinatario necesita NetBird y el certificado privado para abrirlos.

## Operación

Los tokens se renuevan sin contraseña mediante el consentimiento delegado
existente. Microsoft puede revocarlo o exigir una nueva autenticación; en ese caso
repetir el asistente. El servicio nunca inicia un nuevo flujo interactivo desde
un worker. Revocar la autorización en Microsoft y deshabilitar la entrega privada
cuando corresponda. Proteger el volumen y la clave de cifrado; no adjuntarlos a
correos ni subirlos a GitHub. Una conexión válida no prueba entrega final: revisar
recepción, correo no deseado y el estado de la entrega.

Referencias oficiales:
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
