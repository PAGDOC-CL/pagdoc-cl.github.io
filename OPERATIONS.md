# PAGDOC — Runbook operativo (borrador)

**Este documento describe el objetivo de operación privada. No significa que el backend esté actualmente desplegado.**

## Inicio seguro
Antes de arrancar un entorno privado deben existir como secretos externos al repositorio:
- `PAGDOC_SECRET_KEY`;
- `PAGDOC_ENCRYPTION_KEY`;
- URL/credenciales PostgreSQL;
- credenciales del almacenamiento privado;
- configuración del servicio antimalware si aplica.

Las migraciones se aplican con `python -m alembic upgrade head` antes de iniciar la aplicación.

## Comprobaciones de salud
- API responde en `/health`.
- PostgreSQL acepta conexión y está en la revisión Alembic esperada.
- almacenamiento privado puede escribir/leer una sonda no sensible.
- el sistema de análisis de archivos está disponible antes de aceptar cargas.
- no existen migraciones pendientes ni errores críticos de seguridad.

## Respaldos
Objetivo para producción:
1. generar backup PostgreSQL consistente;
2. cifrarlo o guardarlo en un destino cifrado y privado;
3. registrar fecha, tamaño, hash e identificador de backup;
4. mantenerlo fuera del repositorio y fuera del mismo punto único de falla que la base principal;
5. aplicar periodo de retención definido;
6. verificar restauración de manera periódica.

La CI de PAGDOC usa una instancia PostgreSQL temporal para comprobar el ciclo `pg_dump` → recreación de base → `pg_restore` con un dato ficticio de control.

## Restauración
- restaurar siempre primero en un entorno aislado;
- ejecutar verificación de esquema/migraciones;
- comprobar conteos y datos de control;
- verificar aislamiento por tenant;
- reconciliar eliminaciones/retenciones realizadas después de la fecha del backup;
- habilitar tráfico solo después de controles funcionales y de seguridad.

## Rotación de secretos
Ante sospecha o exposición:
- rotar credenciales afectadas;
- revocar sesiones activas;
- regenerar secretos de aplicación cuando corresponda;
- evaluar impacto sobre datos cifrados antes de rotar claves de cifrado;
- conservar auditoría de la acción sin copiar el secreto comprometido.

## Incidente de cuenta
- desactivar usuario si es necesario;
- revocar sus sesiones;
- restablecer contraseña mediante flujo autorizado;
- restablecer MFA si el segundo factor se perdió;
- revisar eventos de auditoría del tenant;
- no enviar credenciales por correo ni mensajería no controlada.

## Incidente documental
Si un archivo resulta sospechoso:
- impedir nuevas descargas;
- poner el objeto en cuarentena lógica;
- preservar hash y metadatos para investigación;
- no abrirlo manualmente en estaciones de trabajo;
- ejecutar análisis antimalware en entorno controlado;
- registrar resolución y versión reemplazada cuando corresponda.

## Criterios de recuperación
Una restauración no se considera exitosa solo porque la base inicia. Deben pasar como mínimo migraciones, inicio de sesión, aislamiento multiempresa, permisos, consulta de documentos, auditoría y una lectura controlada de almacenamiento.
