# Seguridad de PAGDOC

PAGDOC está en desarrollo. El repositorio público contiene una landing, una demostración con información ficticia y código de un backend que **no está desplegado para producción**.

## Regla principal

No publicar ni adjuntar en este repositorio:
- datos personales reales;
- RUT, números de identificación, teléfonos o domicilios de trabajadores;
- contratos, exámenes, certificados, liquidaciones o documentación laboral real;
- información confidencial de clientes o proyectos;
- contraseñas, tokens, claves API, archivos `.env`, cookies o secretos;
- bases de datos, respaldos o archivos privados.

## Reporte de vulnerabilidades

No incluir secretos ni información personal al describir una vulnerabilidad. Hasta habilitar un canal privado formal, cualquier reporte público debe limitarse a una descripción reproducible usando exclusivamente datos ficticios.

## Límites del prototipo

La presencia de controles en el código no significa que el producto esté autorizado para procesar información real. Antes de una beta con documentación empresarial deben completarse, entre otros controles:
- infraestructura privada y HTTPS;
- sesiones revocables, MFA y protección contra fuerza bruta;
- PostgreSQL y migraciones;
- almacenamiento privado cifrado y análisis antimalware;
- respaldos y restauración probada;
- monitoreo y auditoría ampliada;
- pruebas de seguridad y aislamiento multiempresa;
- políticas de privacidad, retención y eliminación.

## Datos de demostración

Los nombres, proyectos, vehículos y registros visibles en `demo.html` son ficticios y existen únicamente para demostrar la interfaz.

## Dependencias

Las dependencias se prueban mediante GitHub Actions. Los cambios de seguridad deben mantener la suite automatizada en verde antes de considerarse integrados.
