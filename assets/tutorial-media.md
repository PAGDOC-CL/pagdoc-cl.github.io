# Videos del tutorial inicial

Trece clips MP4 H.264, 1280 × 720, 12 fps, sin audio, de 15 o 20 segundos.
Cada módulo tiene una guía visual animada con instrucciones en español y datos
ficticios. Son representaciones esquemáticas de los flujos; no grabaciones de
sesiones ni documentos reales. No contienen material de terceros.

Solo aparecen dentro del tutorial inicial, sin reproducción automática ni botón
permanente en la plataforma. Los controles nativos permiten reproducir, pausar y
ampliar. La transcripción de cada video está disponible bajo el reproductor.
Al cambiar de paso, cerrar la ventana u ocultar la pestaña, se pausa el video.

Planificador, documentos y pendientes tienen variantes de consulta y edición.
La elección depende de las capacidades reales de la sesión. Los videos no
ejecutan acciones ni conceden permisos. El cierre y las integraciones muestran
los controles pendientes sin afirmar que estén operativos.

Las instrucciones están en `tutorial-lessons.json`. Para regenerar los clips:

```bash
python3 tools/build_tutorial_media.py
```

El generador requiere Pillow, ffmpeg con libx264 y la fuente DejaVu Sans. No hace
conexiones de red. Los MP4 y el catálogo se sirven desde el mismo origen; no se
requieren servicios externos, reproductores embebidos ni suscripciones.
