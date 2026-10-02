from __future__ import annotations

import unittest

from el_bienvenidor.ui.guest_form import normalize_intake, sanitize_field


class GuestFormTests(unittest.TestCase):
    def test_sanitize_strips_noise_and_limits_length(self) -> None:
        self.assertEqual(sanitize_field("  Ada   Lovelace!!  "), "Ada Lovelace!!")
        self.assertEqual(sanitize_field("ACME @ Chile"), "ACME @ Chile")
        self.assertIsNone(sanitize_field("   "))
        self.assertEqual(sanitize_field("", required=True), "VISITANTE")
        self.assertEqual(len(sanitize_field("A" * 80) or ""), 40)
        self.assertNotIn("<", sanitize_field("Ana <script>") or "")

    def test_normalize_intake_fills_carnet_fields(self) -> None:
        intake = normalize_intake("ada lovelace", " Analytical Engines ", "Ingeniera")
        self.assertEqual(intake.guest_name, "ada lovelace")
        self.assertEqual(intake.organization, "Analytical Engines")
        self.assertEqual(intake.role, "Ingeniera")


if __name__ == "__main__":
    unittest.main()
