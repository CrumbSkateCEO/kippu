#!/usr/bin/env python3
"""Script interactivo para probar la síntesis de voz (Piper TTS), velocidad y el diccionario fonético Spanglish."""

import sys
import time
from pathlib import Path

# Asegurar importación de src/
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from viernes.voice.speaker import VoiceSpeaker, limpiar_texto_para_tts, cargar_diccionario_fonetico

DEMO_TEXT = (
    "Hola, soy Viernes. Presentamos CrumbSkate, una plataforma de e-commerce full-stack construida con "
    "React, Vite y Tailwind CSS en el frontend, y Node.js con Express y PostgreSQL en NeonTech en el backend. "
    "Además, nuestro fotomatón Kippu funciona con MediaPipe bajo Clean Architecture y Photo Booth, "
    "mientras yo razono con Ollama, escucho con Whisper y reproduzco con PyAudio."
)


def banner(speed: float) -> None:
    print("=" * 72)
    print("   🎙️  PROBADOR DE VOZ Y DICCIONARIO FONÉTICO (PIPER TTS)  🎙️")
    print("=" * 72)
    dic = cargar_diccionario_fonetico()
    cant = len([k for k in dic.keys() if not k.startswith("_")])
    print(f"Diccionario cargado con {cant} reglas de pronunciación Spanglish.")
    print(f"Ritmo de lectura explicativo: length_scale={speed} (>1.0 más pausado, <1.0 más rápido)\n")


def probar_frase(speaker: VoiceSpeaker, frase: str) -> None:
    frase_limpia = limpiar_texto_para_tts(frase)
    print("\n" + "-" * 72)
    print(f"📝 TEXTO ORIGINAL:\n   \"{frase}\"")
    print(f"🔊 TEXTO A FONETIZAR (TTS):\n   \"{frase_limpia}\"")
    print(f"⏱️  Ritmo de habla: length_scale={speaker.length_scale}")
    print("-" * 72)
    print("🗣️  Reproduciendo por el altavoz...")
    speaker.speak(frase)
    speaker.wait_until_done()
    print("✅ Reproducción finalizada.\n")


def main() -> None:
    # Parsing simple de argumentos
    args = sys.argv[1:]
    initial_speed = 1.18

    # Soporte para --speed <float> o -s <float>
    if "--speed" in args:
        idx = args.index("--speed")
        if idx + 1 < len(args):
            try:
                initial_speed = float(args[idx + 1])
                del args[idx:idx + 2]
            except ValueError:
                pass
    elif "-s" in args:
        idx = args.index("-s")
        if idx + 1 < len(args):
            try:
                initial_speed = float(args[idx + 1])
                del args[idx:idx + 2]
            except ValueError:
                pass

    banner(initial_speed)

    print("Iniciando motor de voz Piper (cargando modelo Daniela es_AR)...")
    speaker = VoiceSpeaker(length_scale=initial_speed)
    time.sleep(1.5)
    print("¡Motor listo!\n")

    try:
        if args:
            if args[0] in ("--demo", "-d"):
                probar_frase(speaker, DEMO_TEXT)
            else:
                texto = " ".join(args)
                probar_frase(speaker, texto)
            return

        print("Comandos disponibles:")
        print("  - Escribe cualquier frase para escucharla.")
        print("  - 'demo'         : Lee la presentación técnica completa de prueba.")
        print("  - 'vel <numero>' : Cambia la velocidad (ej: 'vel 1.25' más pausado, 'vel 1.10' más rápido).")
        print("  - 'dict'         : Muestra todas las palabras del diccionario fonético.")
        print("  - 'salir'        : Salir del probador.\n")

        while True:
            try:
                entrada = input("👉 Ingresa una frase: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not entrada:
                continue

            if entrada.lower() in ("salir", "exit", "quit", "q"):
                break

            if entrada.lower() == "demo":
                probar_frase(speaker, DEMO_TEXT)
            elif entrada.lower().startswith("vel ") or entrada.lower().startswith("speed "):
                partes = entrada.split()
                if len(partes) >= 2:
                    try:
                        nueva_vel = float(partes[1])
                        speaker.set_speed(nueva_vel)
                        print(f"⚡ Velocidad actualizada a length_scale={nueva_vel}. Probá una frase ahora!\n")
                    except ValueError:
                        print("⚠️ Valor inválido. Usa un número decimal (ej: vel 1.25 o vel 1.15).\n")
            elif entrada.lower() in ("dict", "diccionario"):
                dic = cargar_diccionario_fonetico()
                print("\n📖 Reglas fonéticas actuales:")
                for k, v in sorted(dic.items(), key=lambda i: i[0].lower()):
                    if not k.startswith("_"):
                        print(f"   • {k:<25} ➔ {v}")
                print()
            else:
                probar_frase(speaker, entrada)

    finally:
        print("\nCerrando motor de voz...")
        speaker.stop()
        print("¡Listo! Hasta la próxima.")


if __name__ == "__main__":
    main()
