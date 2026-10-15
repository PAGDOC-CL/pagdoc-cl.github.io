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

### Mantener abierta la instancia local

Para usar PAGDOC durante una sesión de trabajo, ejecuta en PowerShell:

```powershell
.\PAGDOC.ps1 -Action Run
```

Espera a que los contenedores estén saludables y abre `https://localhost:8443/app`. Conserva esa ventana abierta. `Run` arranca la misma instalación y mantiene un proceso de Ubuntu en primer plano; no crea otra base ni cambia credenciales. Los servicios de systemd por sí solos no mantienen viva una instancia WSL, según la [documentación de Microsoft](https://learn.microsoft.com/en-us/windows/wsl/systemd). Esto puede explicar una conexión rechazada después de terminar los comandos de inicio.

Ctrl+C termina la sesión en primer plano. Para detener los contenedores de forma explícita usa `Stop`; sus volúmenes se conservan. `Run` no instala arranque automático ni mantiene el equipo disponible cuando Windows está apagado o suspendido. El arranque en Windows requiere comprobarse en el equipo final.

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

### Preparar antivirus y almacenamiento cifrado

La imagen privada monta un volumen separado `file_objects` en `/var/lib/pagdoc-files`, propiedad del usuario de la API y con permisos privados. Los archivos se cifran antes de escribirse. La clave sigue en la configuración privada existente: no la cambies ni la publiques. Los directorios compartidos y los enlaces simbólicos se rechazan.

ClamAV se inicia solo al solicitar el perfil opcional `files`. No publica puertos en Windows ni fuera de Docker. Antes de iniciarlo comprueba los recursos de Ubuntu con `free -h` y `df -h /var/lib/docker`. Reserva al menos 4 GiB de RAM disponible para este paso y espacio para la imagen, las firmas y los archivos; ClamAV recomienda aproximadamente 5 GiB de espacio libre para su aplicación. No contrata servicios ni pruebas de pago.

Después de actualizar y reconstruir PAGDOC, desde la misma ventana de Ubuntu:

```bash
cd "$HOME/pagdoc-private" &&
bash deployment/local/control.sh files-start &&
bash deployment/local/control.sh files-check
```

La primera descarga y actualización de firmas puede tardar varios minutos y requiere Internet. `files-start` rechaza el inicio si Ubuntu no dispone de 4 GiB de RAM disponible. `files-check` analiza un PDF ficticio, verifica su cifrado y lectura, comprueba el rechazo de la cadena inocua de prueba antivirus EICAR en memoria y elimina el objeto ficticio. No incorpora los ZIP ni modifica documentos existentes.

El adaptador exige una respuesta limpia completa y una base de firmas cargada con fecha verificable de los últimos siete días. Una desconexión, respuesta incompleta, límite excedido o firma antigua bloquea el almacenamiento. El antivirus reduce el riesgo, pero no valida las fechas ni acredita documentos.

Esta preparación **no habilita cargas ni descargas HTTP**. Faltan las rutas autenticadas y sus permisos, el flujo de empresa/vehículos y el respaldo externo con restauración. SharePoint y los envíos externos siguen pendientes. No copies los ZIP al repositorio. Incluye el volumen `file_objects` y la configuración de cifrado en el futuro respaldo cifrado externo; respaldar solo PostgreSQL no recupera los archivos.

Referencias: [ClamAV en Docker y recursos](https://docs.clamav.net/manual/Installing/Docker.html), [protocolo de análisis](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).

La carga binaria y SharePoint siguen deshabilitados. Este paso prepara y comprueba el servidor, pero no declara la plataforma apta para documentación real. Faltan integrar y comprobar el flujo de archivos en el equipo final, un respaldo externo con restauración comprobada, autorización Microsoft corporativa y un piloto completo de permisos y recuperación. No copies los ZIP a la carpeta del repositorio.

Conserva una copia cifrada independiente de la base de datos **y** del archivo de configuración, que contiene la clave de cifrado. Los volúmenes en el mismo equipo no son un respaldo externo. Las plantillas de respaldo están en `deployment/`, pendientes de configurar y verificar en el equipo.

### Respaldo cifrado en el SSD de Windows

El asistente `deployment/local/backup.py` crea una copia local con AES-256-GCM y una clave derivada de una contraseña privada mediante scrypt. Esta operación cifra el archivo de respaldo; no cambia el cifrado completo de Windows ni del SSD. La copia en el mismo disco no protege frente a su pérdida o falla física.

Instala la dependencia gratuita de Ubuntu una sola vez:

```bash
sudo apt-get update && sudo apt-get install -y python3-cryptography
```

Con PAGDOC iniciado, desde Ubuntu, cambia `TU_USUARIO` por la carpeta real del usuario de Windows:

```bash
cd "$HOME/pagdoc-private" &&
python3 deployment/local/backup.py create "/mnt/c/Users/TU_USUARIO/PAGDOC_Respaldos"
```

El asistente solicita una contraseña de respaldo de al menos 16 caracteres y su confirmación. No la muestra, no la acepta como argumento ni la guarda en variables de entorno o en el respaldo. Consérvala por separado: perderla impide abrir la copia. No la envíes por mensajes.

La copia incluye el volcado PostgreSQL, los objetos cifrados, la configuración con las claves necesarias para recuperarlos y los datos de Caddy con los certificados locales. Pausa brevemente la API y el proxy para tomar una copia consistente, y los reinicia incluso si falla la captura. No detiene PostgreSQL ni borra volúmenes. Evita otros comandos administrativos que escriban en la base durante la copia.

Antes de mostrar `OK`, el asistente comprueba la autenticidad del cifrado, los hashes del contenido y una restauración PostgreSQL real en un contenedor temporal sin red, sin puertos publicados y con datos en memoria. Compara recuentos y descifra cada archivo registrado para comprobar su tamaño y hash. El contenedor temporal se elimina al terminar; la base original no se reemplaza. La verificación requiere memoria suficiente para esa copia temporal de la base.

El destino de Windows recibe únicamente el archivo cifrado `.pagdoc.enc`. Los temporales sin cifrar se crean en un directorio privado de Ubuntu y se eliminan al finalizar; esto no promete borrado físico seguro ante una interrupción o un SSD. No publiques el respaldo, pues incluye material de recuperación sensible aunque esté cifrado.

Para volver a comprobar una copia existente:

```bash
python3 deployment/local/backup.py verify "/mnt/c/Users/TU_USUARIO/PAGDOC_Respaldos/NOMBRE_DEL_RESPALDO.pagdoc.enc"
```

La comprobación nunca restaura sobre el servidor activo. Una recuperación de producción se debe preparar en una instancia privada separada y verificar antes de cambiar el servicio. Este asistente no programa tareas automáticas ni envía copias a SharePoint.

## Habilitar archivos privados de empresa y vehículos

Después de comprobar el antivirus, el almacenamiento y el respaldo, actualiza el código y reconstruye la API. La migración `0010_file_subjects` agrega una tabla de vínculos; conserva los documentos, usuarios y archivos existentes.

```bash
cd "$HOME/pagdoc-private" &&
git pull --ff-only &&
bash deployment/local/control.sh start &&
bash deployment/local/control.sh files-enable
```

`files-enable` comprueba otra vez ClamAV y el almacenamiento, habilita la función en el archivo privado de configuración sin cambiar claves, y reinicia la API con esa opción. La función está deshabilitada de manera predeterminada. Si el antivirus no completa un análisis limpio con firmas vigentes, el archivo no se guarda.

En `https://localhost:8443/app`, recarga con Ctrl+F5 y abre **Empresa y vehículos**. Registra o selecciona el vehículo cuando corresponda, registra el documento y adjunta su archivo. Se admiten PDF, PNG, JPEG, DOCX y XLSX de hasta 15 MiB; no macros, archivos cifrados ni paquetes Word/Excel con contenido activo o expansión excesiva. Esta sección no acepta ZIP como carga masiva. La importación por lotes y SharePoint siguen pendientes.

Administradores y editores pueden registrar y adjuntar; revisores y visores con permiso documental pueden consultar versiones y descargar. Los planificadores no tienen acceso documental. Cada operación comprueba empresa y sesión; las escrituras exigen CSRF. Las patentes existentes no se fusionan automáticamente.

Cada archivo se guarda como una nueva versión cifrada después del análisis. Una carga con una versión esperada antigua devuelve conflicto sin sobrescribir datos. Las versiones previas se conservan. Cada descarga requiere autenticación, se audita, comprueba tamaño y hash, y se entrega como adjunto sin caché. La interfaz no publica rutas del almacenamiento ni enlaces públicos con credenciales.

Los documentos comienzan pendientes. Cambiar el archivo invalida la aprobación previa, y un documento de este módulo sin archivo no puede aprobarse. Las fechas se registran desde evidencia verificada: no se asigna un año de vigencia automáticamente. La aprobación, la fecha y el cierre de servicio siguen siendo controles separados.

Primero comprueba el flujo con un documento ficticio en el equipo final. Al incorporar documentos reales, conserva sus fuentes y crea después un nuevo respaldo cifrado: la copia anterior no incluye los archivos añadidos posteriormente. Esto no declara completadas MFA, la conexión corporativa SharePoint, el arranque automático ni el acceso desde otros equipos.

### Referencias técnicas

- [Docker Engine en Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
- [Aplicaciones WSL desde Windows](https://learn.microsoft.com/en-us/windows/wsl/networking).
- [Certificados locales de Caddy](https://caddyserver.com/docs/automatic-https#local-https).

La CI construye los contenedores y comprueba migraciones, HTTPS con el certificado local, ingreso con usuario ficticio y rechazo de solicitudes sin sesión. Windows/WSL y el navegador del equipo final requieren verificación allí.

### Identidad de empresa y carga por lotes

Después de actualizar y ejecutar `bash deployment/local/control.sh start`, la
migración aditiva `0011_tenant_branding` conserva los registros existentes. Tras
iniciar sesión, el menú muestra el nombre de la empresa y «Gestionado con PAGDOC».
Un administrador puede ir a **Mi seguridad → Cambiar logo de empresa**, seleccionar
el logo original PNG/JPEG de hasta 2 MiB y guardarlo. El archivo pasa por ClamAV,
se cifra con la clave existente y se sirve con sesión dentro de su empresa.
La casilla **Mostrar también este logo y el nombre de empresa en la pantalla de
acceso** autoriza mostrar únicamente esa identidad corporativa antes del acceso;
los documentos y las rutas de archivos continúan exigiendo sesión. Si varias
empresas activan esa casilla en el mismo servidor, el acceso no elige una al azar.
Las versiones anteriores se conservan. El logo nunca se incorpora a GitHub Pages.
Si aún no se ha cargado el original, se muestra el nombre de la empresa.

En **Empresa y vehículos → Cargar varios archivos** se pueden seleccionar entre
1 y 250 documentos, hasta 15 MiB cada uno y 250 MiB en total. Extraer primero los
ZIP en el computador. **Añadir carpeta y subcarpetas** incluye todos los archivos
bajo la carpeta elegida; se puede repetir para acumular distintas carpetas en una
misma carga. **Añadir archivos** permite combinarlos con archivos sueltos. Los
botones **Quitar** y **Vaciar selección** permiten revisar la cola antes de guardar.
Los archivos no admitidos deben quitarse explícitamente; no se omiten en silencio.

Para documentos de **Empresa**, todas las carpetas se vinculan a la empresa actual.
Para **Vehículos**, una sola carpeta usa el selector de vehículo general. Si hay
varios grupos de origen, cada grupo muestra su propio selector y todos deben tener
una asignación explícita antes de comenzar. Los grupos se forman con los dos
primeros niveles de la ruta relativa cuando existen subcarpetas. El nombre de una
carpeta no asigna patentes ni fusiona vehículos. Las carpetas con la misma patente
siguen necesitando su asignación explícita.

La ruta relativa de cada archivo se conserva en su título, hasta 200 caracteres;
el nombre del archivo puede tener hasta 160. Los archivos con el mismo nombre en
carpetas distintas se conservan por separado. Elegir otra vez la misma ruta se
rechaza antes de agregarla a la cola. La organización del servidor sigue siendo
por documentos; no se crean carpetas navegables. Cada archivo crea un documento
independiente, pendiente de revisión y sin fecha de vencimiento inferida.

Antes de guardar, PAGDOC compara cada ruta dentro de la empresa o vehículo
seleccionado. Si existe un archivo diferente en ese destino, muestra las rutas
y exige confirmar el reemplazo. Actualiza el mismo documento, conserva versiones
anteriores y deja la nueva versión pendiente de revisión. Si los bytes son
idénticos, lo omite sin crear una versión. Si el destino cambia después de la
comprobación, detiene la escritura y exige comprobar de nuevo. Los registros
antiguos ambiguos requieren revisión manual; no se elige uno al azar.

El lote procesa secuencialmente y se detiene en el primer rechazo o interrupción.
Los documentos guardados antes del error se conservan. Un archivo nuevo rechazado
no deja un documento vacío. El cuadro indica cuántos se confirmaron y qué archivo
detuvo el lote. Cerrar, pulsar **Actualizar** y revisar antes de reintentar. Al
volver a seleccionar las mismas rutas y destinos, los archivos idénticos ya
confirmados se omiten. No hay reanudación automática tras cerrar la página.
Mantener Ubuntu y la página abiertos durante la carga.

### Administradores adicionales y tutorial

Después de actualizar e iniciar el servidor, el operador local puede ejecutar:

```bash
bash deployment/local/control.sh provision-members --enable-alerts --emails administrador@example.invalid
```

Sustituir el correo ficticio por los destinatarios autorizados. Este asistente
requiere una sola empresa y un administrador inicial. Crea cuentas activas con
rol administrador y genera contraseñas fuertes que muestra únicamente en la
terminal local. Para cuentas existentes conserva su contraseña, actualiza el rol
y revoca las sesiones anteriores. No envía invitaciones ni contraseñas por correo.
Entregar cada clave por un canal privado. Otro administrador puede restablecer
el acceso desde **Usuarios y acceso**.
El acceso desde otro computador requiere configurar una red privada; `localhost`
solo funciona en el equipo servidor.

El tutorial se abre al primer ingreso en cada navegador y está disponible desde
**Tutorial**. Se adapta a los permisos reales del perfil y cubre documentos,
planificador, revisiones, alertas y seguridad. No concede permisos adicionales.

### Avisos por correo (configuración privada pendiente)

Cada perfil puede activar avisos en **Mi seguridad → Configurar avisos**, elegir
entre 1 y 90 días de anticipación y activar vencidos, próximos a vencer y tareas
atrasadas. Se usa exclusivamente el correo registrado del perfil. Las cuentas
creadas con `--enable-alerts` quedan suscritas, pero no hay envío hasta configurar
una cuenta SMTP existente y autorizada por su proveedor:

```bash
bash deployment/local/control.sh configure-email
bash deployment/local/control.sh start
```

El asistente solicita servidor, puerto TLS 465/587, usuario, remitente y credencial
oculta. Verifica TLS y autenticación sin enviar mensajes. Guarda la configuración
local con permisos 600 y conserva las claves de base de datos y cifrado. No pegar
credenciales en GitHub ni en el chat. La conexión de SharePoint no configura SMTP;
si el proveedor exige OAuth u otro método, esta conexión SMTP no lo sustituye.

El servicio opcional comprueba cada 15 minutos y envía como máximo un resumen por
perfil al día, desde las 09:00 de America/Santiago, si hay alertas. El servidor debe
permanecer encendido. Solo cuenta vencimientos registrados y tareas pendientes;
no deduce fechas desde los archivos ni adjunta documentos. Respeta empresa y
permisos; los perfiles sin lectura documental no reciben conteos documentales.
Los administradores ven tareas de la empresa; los demás solo las asignadas.

La vista previa no envía mensajes. Un intento SMTP incierto queda marcado como
`unknown` y no se reintenta automáticamente ese día para evitar duplicados.
`sent` significa aceptado por SMTP, no una garantía de llegada a la bandeja.
Comprobar una entrega real autorizada y su recepción antes de declarar operativo
el correo. Esta configuración no contrata servicios ni pruebas pagadas.

La pantalla privada conserva el panel azul y sus textos. Incluye un video MP4 de
imágenes industriales ilustrativas generadas, sin texto sobre las fotografías,
con reproducción silenciosa en bucle y control para pausar. Con la preferencia
`prefers-reduced-motion`, se muestra la portada fija hasta pulsar reproducir.
La reproducción se pausa al entrar en la sesión o al ocultar la pestaña.
El video no contiene material documental ni fotografías reales de Mufas Chile.
