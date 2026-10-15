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

En `https://localhost:8443/app`, recarga con Ctrl+F5 y abre **Empresa y vehículos**. Registra o selecciona el vehículo cuando corresponda, registra el documento y adjunta su archivo. Se admiten PDF, PNG, JPEG, DOCX y XLSX de hasta 50 MiB; no macros, archivos cifrados ni paquetes Word/Excel con contenido activo o expansión excesiva. Esta sección no acepta ZIP como carga masiva. La importación por lotes y SharePoint siguen pendientes.

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
1 y 3000 documentos, hasta 50 MiB cada uno, enviados individualmente. Extraer primero los
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

El tutorial se presenta una sola vez por cuenta y queda registrado en el servidor,
incluso si después se usa otro navegador o cambia el rol. Cada paso abre directamente
su módulo: servicios y centros de trabajo, planificador, documentos, revisiones,
alertas y accesos según los permisos reales. Cada paso incluye un video instructivo local, silencioso y con instrucciones
escritas; se reproduce solo al pulsar el control y se pausa al cerrar o cambiar
de paso. Los ejemplos animados usan datos ficticios y tienen transcripción. Los
perfiles de consulta reciben videos de consulta, sin acciones de edición.
No existe un botón fijo en la barra.
Cerrar o finalizar el recorrido no lo vuelve a mostrar. Para una revisión\nsolicitada explícitamente, un usuario autenticado puede abrir\n`https://localhost:8443/app?tutorial=ver`. Ese enlace abre el recorrido según sus\npermisos, conserva la marca de primera presentación y elimina el parámetro de\nrevisión al abrirse. No añade botones ni activa repeticiones automáticas. Se conserva la marca de
los navegadores que ya habían mostrado el tutorial anterior. No concede permisos.

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

### Proyectos, emergencias y servicios programados

El apartado **Proyectos y servicios** incluye tres selecciones: **Proyectos**,
**Servicios de emergencia** y **Servicio programado**. Permite crear proyectos,
filtrar sus servicios y seleccionar la categoría al crear un servicio. Los perfiles
con permiso de planificación pueden crear y clasificar; los de consulta solo leen.

La migración aditiva `0015_service_kind` conserva los servicios existentes con
**Pendiente de clasificar**. No deduce categorías desde nombres ni fechas. En
Proyectos se mantienen visibles todos los servicios vinculados; las otras dos
selecciones muestran únicamente su categoría. Clasificar conserva proyecto, fechas,
personal, documentos y requisitos, y registra la acción con control de versión.
Los servicios cerrados o cancelados no cambian de categoría. Una emergencia no
omite controles documentales ni permite asignaciones fuera del período.

El tutorial y su video de proyectos y servicios explican las tres selecciones,
la creación y clasificación; solo emplean datos ficticios.

### Carga automática, fechas y vista previa

**Empresa y vehículos → Cargar carpeta automática** recibe una carpeta principal
y conserva sus subcarpetas como rutas lógicas. El selector **Carpeta** permite
consultarlas. **Subdivisión por tipo** agrupa lógicamente los documentos por la
clasificación del contenido, sin duplicar ni mover los originales. La detección usa carpetas explícitas de empresa, patentes registradas
y coincidencias exactas con nombres completos de trabajadores o proyectos activos.
No crea identidades ni asigna por similitud. Si falta un trabajador, usa
**Registrar trabajador**; esto crea la ficha operacional, sin cuentas ni
invitaciones. Los proyectos se registran desde **Proyectos y servicios**. Una ruta desconocida o ambigua se
detiene antes de escribir: corregir el destino o usar la selección manual. Los
destinos resueltos y los reemplazos se muestran juntos para una confirmación previa.
Se admiten 3000 archivos por selección y 50 MiB por archivo. La comprobación de destinos se divide en grupos de 250 y los binarios se envían de uno en uno. No se reserva espacio por adelantado: comprueba el disco disponible y mantén abierta la ventana durante la carga.

El perfil local `files` inicia también el servicio **analysis**. Después de escanear
y cifrar un archivo, un trabajador privado lee el PDF, imagen, DOCX o XLSX sin
servicios externos. El cuerpo extraído no se guarda en la base de datos ni en
registros; solo propuestas de tipo y fechas, avisos y confirmaciones. El texto
temporal se procesa en directorios privados sobre tmpfs, con límites de procesos,
memoria, CPU, páginas, tamaño y tiempo. Las fórmulas de Excel no se ejecutan.
Los archivos antiguos también se analizan; cada resultado pertenece a su versión.
Al reiniciar, un bloqueo exclusivo de trabajador permite retomar solo los análisis
interrumpidos, sin duplicar archivos ni borrar resultados completos o confirmados.

Una fecha de vencimiento explícita, única y sin contradicciones, cuyo contenido
confirme también el nombre completo o patente del destino, puede actualizar
la metadata automáticamente. No se usa la fecha de carga ni se asigna un año de
vigencia por defecto. OCR, fechas ambiguas o inválidas, documentos extensos,
lecturas parciales y tipos desconocidos exigen revisión. Un plazo escrito en días
puede proponerse, pero su cómputo debe confirmarse. Las reglas del proyecto y la
aprobación documental siguen siendo una verificación separada.

El semáforo usa 30 días de anticipación: rojo para vencidos; amarillo para próximos
a vencer o casos pendientes; verde solo con fecha aplicada o confirmada y fuera
de ese plazo. **Fechas y semáforo** muestra propuestas y advertencias y permite
al editor confirmar contra el original, con motivo y control de versión/revisión.
Una nueva versión borra la vigencia heredada del archivo anterior y exige un nuevo
análisis y revisión; las versiones originales permanecen en el historial.
La pantalla comprueba el avance cada cinco segundos mientras haya análisis pendientes
visibles, no haya un diálogo abierto y la pestaña esté activa.

**Vista previa** abre páginas PDF renderizadas como imágenes y permite avanzar
antes de descargar el original. Las imágenes tienen límites de dimensiones; Word
y Excel se muestran como texto, sin reproducir su diseño ni ejecutar fórmulas.
Los PDF se consultan por páginas hasta 100; el análisis automático lee hasta 12 y
marca como parciales los más extensos. Todas las vistas exigen sesión, permisos,
empresa correcta e integridad del archivo y se sirven sin caché. Una vista previa
fallida no modifica ni aprueba el documento original.

Las fechas verificadas alimentan los avisos del perfil. El envío de correos sigue
pendiente de configurar y autorizar con el proveedor corporativo.


La carga automática también propone crear fichas de vehículos que falten a partir
de una patente inequívoca en carpetas de vehículos. Muestra las patentes una sola
vez por ficha y exige confirmación conjunta antes de crearlas. Luego presenta
los destinos y reemplazos antes de enviar binarios. Patentes existentes se
reutilizan; las inactivas o ambiguas requieren revisión, sin reactivación ni fusión
automática. Crear una ficha no acredita el vehículo ni inventa su tipo, marca o
modelo. El modo manual agrupa por carpeta de documentos, evitando asignar una
flota completa a un solo vehículo.


El módulo de archivos abre carpetas por destino: una carpeta de empresa y una
por patente con documentos, además de trabajadores/proyectos cuando existan.
Abrir una patente reúne sus documentos incluso si llegaron desde varias carpetas
diferentes. Dentro se pueden recorrer las carpetas de origen, filtrar por tipo y
consultar fechas/semáforos. Inicio vuelve a las carpetas; «Ver todos los documentos»
abre la lista completa. Se aplica a los registros ya cargados sin volver a subir,
mover ni duplicar binarios. El análisis privado sigue en segundo plano; «En cola»
no significa que una fecha esté revisada.

«Cargar en esta carpeta» preselecciona el destino abierto. Un archivo suelto con
un nombre original único dentro de ese destino reutiliza su carpeta asociada y
se muestra como reemplazo a confirmar; conserva versiones y ruta original. Si
hay más de una coincidencia, se bloquea para revisión. No se interpretan nombres
diferentes como el mismo documento.


Las rutas lógicas de carpetas y documentos admiten hasta 1024 caracteres en total
(antes 200). La migración 0018 amplía el título y la ruta de origen; conserva las
asociaciones e identifica rutas por SHA-256 de su forma normalizada para evitar
claves de índice excesivas con Unicode en PostgreSQL. No renombra ni trunca rutas
existentes. El límite individual de nombre de archivo continúa en 160 caracteres.


La validación del lote identifica cada archivo no admitido con su ruta y motivo
(formato, tamaño, archivo vacío, nombre largo o temporal de Office). La acción
«Apartar archivos de esta selección» permite continuar con los restantes, sin
borrar los originales ni enviar archivos antes de revisar nuevamente el lote.
DOC/XLS antiguos y otros tipos no se convierten de forma silenciosa: requieren
convertir una copia a PDF, DOCX o XLSX conservando el original.


Automatizador de fechas (reglas versión 2): alcohol y drogas aplica emisión + 30
días corridos. Requiere emisión explícita y única; fecha de muestra o realización
no sustituye automáticamente a emisión. OCR, identidad dudosa y contradicciones
quedan para revisión. El vencimiento manual de alcohol/drogas también se calcula
y valida a 30 días. La alerta visual usa 7 días para estos exámenes (30 para otros
documentos); el día de vencimiento es amarillo y el siguiente, rojo.
La migración 0019 permite al motor retomar una vez los análisis anteriores. Las
fechas de emisión ya confirmadas se conservan y su vencimiento de drogas se
recalcula con auditoría. No modifica binarios ni aprueba acreditaciones. El panel
muestra cola, documentos analizados y casos para revisión de la empresa.

En cargas de trabajadores también se proponen fichas operacionales por nombre
completo inequívoco en las carpetas de personal. Se confirman juntas, se reutiliza
la identidad existente y no se crean cuentas, invitaciones, RUT ni cargos. Nombres
duplicados, inactivos o carpetas ambiguas requieren revisar la identidad.


### Cambio de contraseña y recuperación por correo

Dentro de la sesión, abre **Mi seguridad → Cambiar mi contraseña**. Se requiere la contraseña actual y, si está habilitado, el segundo factor. La nueva contraseña debe tener entre 12 y 128 caracteres, al menos una mayúscula, un número y un carácter especial. Se cierran todas las sesiones después del cambio; las claves existentes siguen funcionando hasta que su titular las cambie.

**Olvidé mi contraseña** envía un enlace al correo de una cuenta activa, válido por 30 minutos y de un solo uso. No se envían contraseñas, no se inicia sesión automáticamente y el MFA existente se conserva. Un enlace nuevo invalida el anterior. La base de datos guarda únicamente la huella del token; el enlace se lleva en el fragmento de la URL y se retira de la barra al abrirlo.

El envío requiere la cuenta SMTP ya configurada con `control.sh configure-email`. Si no está configurada, la plataforma lo indica y no anuncia un correo enviado. El estado `sent` significa aceptado por SMTP, no llegada garantizada. El flujo no depende de tener activadas las alertas documentales del perfil.

En esta instalación el enlace apunta a `https://localhost:8443/app`, por lo que debe abrirse en el computador que ejecuta PAGDOC. Para un servidor privado accesible con otra dirección, establece `PAGDOC_PASSWORD_RESET_URL` en su URL HTTPS terminada en `/app`, dentro de la configuración privada, y reinicia el servicio. No se construyen enlaces usando cabeceras enviadas por el navegador. No publiques esa configuración ni sus credenciales.

La migración `0020_password_recovery` agrega las solicitudes de recuperación y el control de intentos sin cambiar documentos existentes. Actualiza con `git pull --ff-only` y `bash deployment/local/control.sh start`.

### Claves temporales para usuarios existentes

En **Usuarios y acceso**, el administrador puede seleccionar **Generar clave temporal** para una cuenta activa de su empresa. La confirmación revoca las sesiones del usuario y muestra una clave aleatoria una sola vez. Copia y entrega la clave por un canal privado antes de cerrar la ventana. No se envía correo ni se guarda la clave en texto legible.

La clave vence en 24 horas. Al iniciar sesión, la API permite únicamente consultar la identidad, cambiar la contraseña o cerrar sesión hasta que el titular elija una clave personal. La nueva contraseña debe cumplir los requisitos y ser distinta de la temporal. El segundo factor existente permanece activo. Una clave temporal nueva invalida la anterior; una vencida requiere renovación administrativa o recuperación por correo configurado.

Las cuentas anteriores conservan su acceso hasta que se les genere una clave temporal. La creación de usuarios en la interfaz exige cambio al primer ingreso de forma predeterminada. El administrador actual usa **Mi seguridad** para cambiar su propia clave. La migración `0021_temporary_password` agrega estos controles sin modificar documentos.
