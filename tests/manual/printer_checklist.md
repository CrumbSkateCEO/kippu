# Checklist manual — impresora Windows

1. Configurar la impresora predeterminada en vertical, papel 10x15 cm y escala 100 %.
2. Ejecutar primero `scripts/diagnostic_windows.ps1` y revisar el área imprimible reportada.
3. Ejecutar Kippu con `-RealPrinter`; confirmar que no aparece ningún diálogo de impresión.
4. Probar sin papel, tapa abierta y cola pausada; anotar los flags Win32 mostrados en `logs/kippu.log`.
5. Ante un fallo posterior al envío, buscar `Kippu-<UUID>` en la cola antes de iniciar otro flujo: Kippu no debe reintentar automáticamente.

