from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from PIL import Image

from el_bienvenidor.composition.card_composer import compose_card, validate_card_artifact
from el_bienvenidor.composition.layout import CardLayout
from el_bienvenidor.domain.models import CardData, FaceCrop, JobId


class CardComposerTests(unittest.TestCase):
    def test_composes_300_dpi_card_with_stable_hash(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "card.png"
            crop = FaceCrop(Image.new("RGB", (600, 800), (120, 150, 180)), (0, 0, 600, 800), 0.99)
            artifact = compose_card(
                crop,
                CardData(
                    "¡Bienvenido!",
                    "Ada Lovelace",
                    datetime(2026, 1, 2, tzinfo=timezone.utc),
                    "ABCD1234",
                    organization="Analytical Engine",
                    role="Matemática",
                ),
                CardLayout(),
                output,
                JobId(uuid4()),
            )
            self.assertEqual(artifact.pixel_size, (1181, 1772))
            self.assertEqual(artifact.dpi, (300, 300))
            self.assertTrue(output.is_file())
            self.assertEqual(len(artifact.sha256), 64)
            validate_card_artifact(artifact)
            with Image.open(output) as rendered:
                header = rendered.getpixel((590, 40))
                footer = rendered.getpixel((590, 1740))
                cream = rendered.getpixel((40, 200))
            self.assertLess(header[0], 80)
            self.assertGreater(header[2], 70)
            self.assertLess(footer[0], 80)
            self.assertGreater(sum(cream), 600)


if __name__ == "__main__":
    unittest.main()
