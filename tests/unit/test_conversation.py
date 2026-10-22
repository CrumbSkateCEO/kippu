from __future__ import annotations

import unittest

from viernes.voice.conversation import (
    es_cierre_conversacion,
    es_despertar,
    texto_despues_de_despertar,
)


class ConversationDismissalTests(unittest.TestCase):
    def test_gracias_viernes_eso_es_todo(self) -> None:
        self.assertTrue(es_cierre_conversacion("gracias viernes, eso es todo"))
        self.assertTrue(es_cierre_conversacion("Gracias Viernes. Eso es todo."))
        self.assertTrue(es_cierre_conversacion("eso es todo, gracias"))
        self.assertTrue(es_cierre_conversacion("chau viernes"))
        self.assertTrue(es_cierre_conversacion("podés descansar"))

    def test_no_cierra_pedidos_reales(self) -> None:
        self.assertFalse(es_cierre_conversacion("abrí firefox"))
        self.assertFalse(es_cierre_conversacion("gracias viernes abrí youtube"))
        self.assertFalse(es_cierre_conversacion("gracias por explicar el proyecto"))
        self.assertFalse(
            es_cierre_conversacion(
                "eso es todo lo que tiene el e-commerce o también hay más módulos"
            )
        )

    def test_despertar_y_pedido(self) -> None:
        self.assertTrue(es_despertar("Viernes, abrí YouTube"))
        self.assertTrue(es_despertar("hola viernes"))
        self.assertFalse(es_despertar("abrí youtube"))
        self.assertEqual(
            texto_despues_de_despertar("Hola Viernes, abrí firefox"),
            "abri firefox",
        )
        self.assertEqual(texto_despues_de_despertar("viernes"), "")


if __name__ == "__main__":
    unittest.main()
