# PAGDOC en tu equipo Windows

Esta instalación crea una **instancia privada local**, accesible en `https://localhost:8443/app`, con cuentas y registros propios de la empresa. Usa Ubuntu en WSL 2, Docker Engine, PostgreSQL y Caddy con una autoridad de certificados local. No contrata hosting, no abre el router y no publica documentación real en GitHub Pages. El equipo debe estar encendido y WSL/Docker en ejecución. La carga de documentos requiere los controles adicionales indicados al final.

## 1. Preparar Windows

En PowerShell como administrador:

```powershell
wsl --install -d Ubuntu
```

Reinicia si Windows lo solicita. Abre **Ubuntu** desde Inicio y crea el usuario y contraseña de Linux. Usa una distribución WSL 2; compruébalo con `wsl --list --verbose`. Si Ubuntu indica versión 1, conviértela mediante `wsl --set-version Ubuntu 2`.

Microsoft documenta estos pasos en [Instalar WSL](https://learn.microsoft.com/es-es/windows/wsl/install). El instalador de PAGDOC no puede ejecutar estos pasos desde ChatGPT ni controla tu equipo Windows.

## 2. Descargar e instalar PAGDOC

Descarga [el código del repositorio](https://github.com/PAGDOC-CL/pagdoc-cl.github.io/archive/refs/heads/main.zip), extráelo y abre PowerShell en la carpeta `deployment/windows`. Revisa `PAGDOC.ps1` antes de ejecutarlo. Si Windows bloquea el archivo descargado, usa `Unblock-File .\PAGDOC.ps1` para ese archivo; no cambies la política global del sistema.

```powershell
.\PAGDOC.ps1 -Action Install
.\PAGDOC.ps1 -Action Start
```

Si tu política de PowerShell restringe scripts locales, consulta al administrador del equipo para autorizar este archivo. No se recomienda deshabilitar las restricciones globales. Si Ubuntu tiene otro nombre, añade `-Distribution Ubuntu-24.04` usando el nombre exacto que muestre `wsl --list --quiet`.

La instalación pide tu contraseña de Linux para `sudo`, instala Docker Engine desde su repositorio oficial y conserva el código en `~/pagdoc-private`. No borra instalaciones de contenedores existentes ni actualiza automáticamente una copia ya creada. Los secretos se generan en `~/.config/pagdoc-private/runtime.env`, con permisos privados, y no se imprimen ni se rotan al reiniciar.

La primera descarga y construcción necesita Internet. La base de datos y la API no publican puertos al host. Solo el proxy publica el puerto 8443 en la dirección de bucle local `127.0.0.1`.

## 3. Habilitar HTTPS y crear el administrador de empresa

```powershell
.\PAGDOC.ps1 -Action TrustCertificate
.\PAGDOC.ps1 -Action Provision
```

`TrustCertificate` instala la autoridad local de PAGDOC únicamente en el almacén de confianza de tu usuario Windows. Muestra su huella y no exporta la clave privada. Caddy en un contenedor no puede instalar por sí solo esa confianza en Windows. Es necesario reiniciar el navegador si mantiene una advertencia anterior.

`Provision` pide el nombre de la empresa, el correo del administrador y una contraseña de PAGDOC de al menos 12 caracteres. El correo corporativo es válido como identificador local, pero este registro no verifica el buzón ni conecta Microsoft 365. No se envían correos y no se sobrescriben cuentas. El comando solo permite registrar el primer administrador de una empresa sin usuarios. Los siguientes accesos se gestionan desde su administrador autenticado.

Abre `https://localhost:8443/app`, inicia sesión y configura MFA desde **Mi seguridad**. La interfaz muestra el nombre de la empresa guardado en la base privada. No contiene usuarios, servicios ni documentos de ejemplo precargados.

Para una prueba totalmente ficticia separada sigue disponible `bash deployment/local/control.sh provision-beta`; no es el comando de registro corporativo.

### Actualizar una instalación ya creada

Si tu asistente todavía dice `Fictitious tenant name`, cancélalo con Ctrl+C. Dentro de Ubuntu, ejecuta:

```bash
cd "$HOME/pagdoc-private" &&
git pull --ff-only &&
bash deployment/local/control.sh start &&
bash deployment/local/control.sh provision
```

La actualización conserva la configuración y los volúmenes. Si Git detecta cambios locales o una divergencia, detente y revísalos; no uses reset ni elimines la base para forzar la actualización.

## 4. Comprobar y detener

```powershell
.\PAGDOC.ps1 -Action Status
.\PAGDOC.ps1 -Action Stop
.\PAGDOC.ps1 -Action Start
```

Prueba crear un servicio ficticio, asignar descanso/terreno y registrar asistencia. `Stop` detiene los servicios y conserva los volúmenes. No uses comandos de eliminación de volúmenes o de desregistro de Ubuntu para detener PAGDOC: eliminarían datos. Tras reiniciar Windows, ejecuta `Start`; aún no se instala un arranque automático de Windows.

## Antes de incorporar los documentos reales

La carga binaria y SharePoint siguen deshabilitados. Este paso prepara y comprueba el servidor, pero no declara la plataforma apta para documentación real. Faltan almacenamiento privado y antivirus integrados, respaldo externo con restauración comprobada, autorización Microsoft corporativa y un piloto completo de permisos y recuperación. No copies los ZIP a la carpeta del repositorio.

Conserva una copia cifrada independiente de la base de datos **y** del archivo de configuración, que contiene la clave de cifrado. Los volúmenes en el mismo equipo no son un respaldo externo. Las plantillas de respaldo están en `deployment/`, pendientes de configurar y verificar en el equipo.

## Referencias

- [Docker Engine en Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
- [Aplicaciones WSL desde Windows](https://learn.microsoft.com/en-us/windows/wsl/networking).
- [Certificados locales de Caddy](https://caddyserver.com/docs/automatic-https#local-https).

La CI construye los contenedores y comprueba migraciones, HTTPS con el certificado local, ingreso con usuario ficticio y rechazo de solicitudes sin sesión. Windows/WSL y el navegador del equipo final requieren verificación allí.
