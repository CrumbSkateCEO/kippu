# Submódulo de control del sistema operativo para Viernes.

from viernes.system.computer_control import (
    OS_FAMILY,
    OS_RESUMEN,
    abrir_aplicacion,
    abrir_navegador,
    buscar_en_internet,
    cerrar_aplicacion,
    cerrar_pestana_navegador,
    detectar_os,
    ejecutar_comando,
    info_sistema,
    listar_procesos,
)

__all__ = [
    "OS_FAMILY",
    "OS_RESUMEN",
    "detectar_os",
    "info_sistema",
    "ejecutar_comando",
    "abrir_aplicacion",
    "cerrar_aplicacion",
    "abrir_navegador",
    "buscar_en_internet",
    "cerrar_pestana_navegador",
    "listar_procesos",
]
