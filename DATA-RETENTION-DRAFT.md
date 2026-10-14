# PAGDOC — Borrador de retención y eliminación de datos

**Estado: borrador técnico para diseño.** Los periodos definitivos deben definirse con cada cliente y con la revisión jurídica/contractual correspondiente antes de producción.

## Objetivo

Evitar acumulación indefinida de información y hacer que cada categoría de datos tenga una regla explícita de conservación, archivo o eliminación.

## Estados propuestos
1. **Activo:** necesario para una acreditación, proyecto o relación vigente.
2. **Archivado:** ya no participa en operación diaria, pero existe una razón autorizada para conservarlo temporalmente.
3. **Programado para eliminación:** terminó su periodo de conservación y está a la espera del proceso automático/controlado.
4. **Eliminado:** contenido retirado del almacenamiento activo; se conserva únicamente un registro mínimo de auditoría cuando corresponda.

## Reglas configurables previstas
Las reglas deben configurarse por tenant y categoría, no quedar codificadas en valores universales. Categorías mínimas:
- usuarios y sesiones;
- proyectos;
- trabajadores;
- vehículos/equipos;
- documentos y versiones;
- auditoría;
- respaldos.

## Bajas
- Desactivar un usuario debe revocar sus sesiones inmediatamente.
- Archivar trabajadores, vehículos y proyectos no debe romper la trazabilidad histórica.
- La eliminación de archivos debe eliminar también versiones y copias temporales controladas, respetando la política de respaldo vigente.
- Una restauración desde backup no debe reactivar automáticamente información ya programada para eliminación; se necesita reconciliación posterior a la restauración.

## Auditoría
Cada operación de archivo, restauración lógica o eliminación debe registrar actor, tenant, recurso, fecha y motivo/código de política, evitando copiar el contenido sensible eliminado dentro del log.

## Respaldos
Los respaldos deben tener su propio periodo de expiración. La capacidad de restauración debe probarse periódicamente con datos ficticios antes de depender de ella para producción.

## Exportación antes de cierre
El futuro flujo de cierre de una empresa/tenant deberá contemplar, con autorización, una exportación de sus datos antes de la eliminación definitiva cuando corresponda.

## Prohibiciones de diseño
- No mantener datos para siempre por defecto.
- No usar el repositorio GitHub público como archivo o respaldo de documentos.
- No conservar secretos, contraseñas en texto plano ni tokens revocados como material recuperable.
- No eliminar auditoría de forma silenciosa ni permitir que un tenant afecte datos de otro tenant.
