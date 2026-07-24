from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from options.management.commands.bootstrap_debsoc import Command
from options.presets import (
    DebSocAsianParliamentaryPreferences,
    DebSocBritishParliamentaryPreferences,
)


class DebSocBootstrapUnitTests(SimpleTestCase):
    def test_username_is_normalized_to_required_format(self):
        self.assertEqual(Command._username_for("Armaan"), "T-Armaan")
        self.assertEqual(Command._username_for("Ruchir Dwivedi "), "T-RuchirDwivedi")
        self.assertEqual(Command._username_for("A. B-C"), "T-ABC")

    def test_password_is_memorable_and_rotated(self):
        with patch(
            "options.management.commands.bootstrap_debsoc.secrets.choice",
            side_effect=["Bright", "Mango", *"Ab3Cd4Ef"],
        ):
            password = Command._new_password()
        self.assertEqual(password, "Bright-Mango-Ab3Cd4Ef")

    def test_bpd_preset(self):
        self.assertEqual(DebSocBritishParliamentaryPreferences.scoring__score_min, Decimal("60"))
        self.assertEqual(DebSocBritishParliamentaryPreferences.scoring__score_max, Decimal("83"))
        self.assertEqual(DebSocBritishParliamentaryPreferences.scoring__score_step, Decimal("1"))
        self.assertEqual(DebSocBritishParliamentaryPreferences.debate_rules__substantive_speakers, 2)
        self.assertFalse(DebSocBritishParliamentaryPreferences.debate_rules__reply_scores_enabled)
        self.assertFalse(DebSocBritishParliamentaryPreferences.motions__enable_motions)
        self.assertEqual(DebSocBritishParliamentaryPreferences.feedback__feedback_from_teams, "orallist")

    def test_apd_preset(self):
        self.assertEqual(DebSocAsianParliamentaryPreferences.scoring__score_min, Decimal("60"))
        self.assertEqual(DebSocAsianParliamentaryPreferences.scoring__score_max, Decimal("83"))
        self.assertEqual(DebSocAsianParliamentaryPreferences.scoring__reply_score_min, Decimal("30"))
        self.assertEqual(DebSocAsianParliamentaryPreferences.scoring__reply_score_max, Decimal("42"))
        self.assertEqual(DebSocAsianParliamentaryPreferences.scoring__reply_score_step, Decimal("0.5"))
        self.assertEqual(DebSocAsianParliamentaryPreferences.debate_rules__substantive_speakers, 3)
        self.assertTrue(DebSocAsianParliamentaryPreferences.debate_rules__reply_scores_enabled)
        self.assertFalse(DebSocAsianParliamentaryPreferences.motions__enable_motions)
        self.assertEqual(DebSocAsianParliamentaryPreferences.feedback__feedback_from_teams, "all-adjs")
