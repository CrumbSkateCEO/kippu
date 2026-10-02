# Checklist manual — desconexión de cámara

1. Ejecutar Kippu con la webcam conectada y confirmar la vista previa espejada.
2. Desconectar el cable USB durante `IDLE`; debe aparecer el estado de cámara y no debe subir el uso de CPU.
3. Reconectar la webcam y esperar los reintentos de 1, 2 y 5 segundos; debe volver a `IDLE`.
4. Iniciar cuenta regresiva, desconectar antes de cero y verificar que no se creó trabajo bajo `data/jobs`.
5. Revisar `logs/kippu.log` y confirmar que no contiene frames ni landmarks.

