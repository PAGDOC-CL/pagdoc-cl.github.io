# PAGDOC — integración privada con SharePoint

## Dos autorizaciones diferentes

1. **SharePoint en ChatGPT:** permite al asistente acceder a los recursos que autoriza la cuenta Microsoft conectada. No entrega esas credenciales al JavaScript del sitio ni al backend.
2. **SharePoint en PAGDOC:** necesita una identidad Microsoft del entorno privado y un proveedor de tokens del servidor, junto con permisos delimitados al sitio/biblioteca/carpeta autorizados. No está configurada ni activada.

Una cuenta Microsoft personal con OneDrive no demuestra acceso a un sitio SharePoint corporativo. El propietario deberá conectar la cuenta de trabajo con acceso al sitio y aprobar la identidad/biblioteca de la aplicación privada.

## Adaptador preparado

`backend/sharepoint_adapter.py` implementa consulta de metadatos mediante Microsoft Graph v1.0:

- verifica sitio HTTPS canónico y correspondencia del sitio devuelto;
- restringe la navegación al drive y carpeta raíz configurados en el servidor;
- utiliza un proveedor de tokens inyectado sin guardar ni registrar el token;
- no sigue redirecciones ni acepta nextLinks arbitrarios;
- devuelve únicamente metadatos seleccionados; no exporta URLs temporales de descarga;
- falla de forma cerrada si faltan credenciales, permisos o respuesta válida;
- las pruebas emplean transporte simulado y datos ficticios, no la biblioteca empresarial.

Referencias técnicas: [sitio por ruta](https://learn.microsoft.com/en-us/graph/api/site-getbypath?view=graph-rest-1.0) y [contenido de carpeta](https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?view=graph-rest-1.0).

## Procedimiento antes de habilitar archivos

- Resolver el sitio y biblioteca usando la cuenta corporativa autorizada; comprobar su propietario y permisos efectivos.
- Elegir una carpeta privada de pruebas y un alcance de aplicación mínimo. No crear enlaces anónimos.
- Autorizar y configurar la identidad del servidor fuera del repositorio. No copiar tokens de ChatGPT al código.
- Integrar análisis antimalware real, límites, validación de firmas, control de versiones, hashes y auditoría por descarga.
- Ejecutar un piloto con archivos exclusivamente ficticios, incluyendo malware de prueba controlado y pruebas de permisos negativos en un entorno aislado.
- Mantener la API binaria bloqueada hasta verificar todos esos controles.

No se han movido, renombrado, publicado ni modificado documentos de Mufas Chile como parte de esta implementación.
