from __future__ import annotations

import unittest
from unittest.mock import patch

from viernes.system.computer_control import (
    OS_FAMILY,
    detectar_os,
    ejecutar_comando,
    info_sistema,
    abrir_navegador,
    buscar_en_internet,
)


class ComputerControlTests(unittest.TestCase):
    def test_detecta_familia_conocida(self) -> None:
        info = detectar_os()
        self.assertIn(info["family"], {"linux", "windows", "macos"})
        self.assertEqual(info["family"], OS_FAMILY)
        self.assertIn(info["pretty"], info_sistema())
        self.assertTrue(info["resumen"])

    def test_bloquea_comandos_destructivos(self) -> None:
        out = ejecutar_comando("rm -rf /")
        self.assertIn("bloqueado", out.lower())
        out = ejecutar_comando("shutdown now")
        self.assertIn("bloqueado", out.lower())

    def test_abrir_navegador_agrega_https(self) -> None:
        with patch("viernes.system.computer_control.webbrowser.open_new_tab") as mock_open:
            msg = abrir_navegador("youtube.com")
        mock_open.assert_called_once_with("https://youtube.com")
        self.assertIn("https://youtube.com", msg)

    def test_buscar_abre_google(self) -> None:
        with patch("viernes.system.computer_control.webbrowser.open_new_tab") as mock_open:
            msg = buscar_en_internet("crumbskate")
        self.assertIn("google.com/search", mock_open.call_args[0][0])
        self.assertIn("crumbskate", mock_open.call_args[0][0])
        self.assertIn("crumbskate", msg)


if __name__ == "__main__":
    unittest.main()
