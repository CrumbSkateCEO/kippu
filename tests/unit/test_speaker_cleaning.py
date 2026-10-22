from __future__ import annotations

import tempfile
import shutil
import importlib.util
from pathlib import Path
import unittest

from viernes.voice.speaker import limpiar_texto_para_tts, cargar_diccionario_fonetico


class SpeakerCleaningTests(unittest.TestCase):
    def test_diccionario_fonetico_values(self) -> None:
        dic = cargar_diccionario_fonetico()
        expected_pairs = {
            "Kippu": "Kipu",
            "Jarvis": "Yárvis",
            "CrumbSkate": "Crámb eskeit",
            "e-commerce": "i cómers",
            "React": "Ríact",
            "Node.js": "Noud yei es",
            "Express": "Exprés",
            "NeonTech": "Níon tek",
            "PostgreSQL": "Póstgres ese cu éle",
            "Ollama": "Olama",
            "backend": "bákend",
            "frontend": "fróntend",
            "MediaPipe": "Mídia paip",
            "Clean Architecture": "Clin arquitéctiur",
            "Photo Booth": "Fóto bút",
            "PyAudio": "Pai áudio",
            "F.R.I.D.A.Y.": "Fráidei",
            "Tailwind CSS": "Téilwind ce ese ese",
        }
        for k, v in expected_pairs.items():
            self.assertIn(k, dic)
            self.assertEqual(dic[k], v)

    def test_limpiar_markdown(self) -> None:
        texto = "*Hola* _amigos_ #1 \"proyecto\" 'escolar' ~prueba~"
        esperado = "Hola amigos 1 proyecto escolar prueba"
        self.assertEqual(limpiar_texto_para_tts(texto), esperado)

    def test_optimizar_prosodia_saltos_linea_y_puntuacion(self) -> None:
        texto = "Línea 1.\nLínea 2... Línea 3."
        esperado = "Línea 1, Línea 2, Línea 3."
        self.assertEqual(limpiar_texto_para_tts(texto), esperado)

    def test_puntos_medios_convertidos_a_comas(self) -> None:
        texto = "Hola a todos. Soy Jarvis. Bienvenidos a Kippu."
        esperado = "Hola a todos, Soy Yárvis, Bienvenidos a Kipu."
        self.assertEqual(limpiar_texto_para_tts(texto), esperado)

    def test_nodejs_y_terminos_tecnicos_fonetica(self) -> None:
        texto = "Desarrollamos con React, Node.js y Express en el backend y frontend."
        esperado = "Desarrollamos con Ríact, Noud yei es y Exprés en el bákend y fróntend."
        self.assertEqual(limpiar_texto_para_tts(texto), esperado)

    def test_spanglish_tecnico_avanzado(self) -> None:
        texto = "Kippu usa MediaPipe con Clean Architecture y Photo Booth."
        esperado = "Kipu usa Mídia paip con Clin arquitéctiur y Fóto bút."
        self.assertEqual(limpiar_texto_para_tts(texto), esperado)

    def test_missing_dictionary_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src_speaker = Path(__file__).resolve().parent.parent.parent / "src" / "viernes" / "voice" / "speaker.py"
            dst_speaker = Path(tmpdir) / "speaker.py"
            shutil.copy(src_speaker, dst_speaker)

            spec = importlib.util.spec_from_file_location("isolated_speaker", dst_speaker)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            dic = mod.cargar_diccionario_fonetico()
            self.assertEqual(dic, {})
            resultado = mod.limpiar_texto_para_tts("Hola. Mundo... #test")
            self.assertEqual(resultado, "Hola, Mundo, test")


if __name__ == "__main__":
    unittest.main()
