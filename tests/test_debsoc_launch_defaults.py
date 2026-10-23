"""Fast deployment-preset contract checks, independent of a live database."""
import ast
import pathlib
import unittest


class LaunchDefaults(unittest.TestCase):
    def test_private_submissions_and_individual_ap_ballots(self):
        source = pathlib.Path(__file__).resolve().parents[1] / "tabbycat/options/presets.py"
        classes = {node.name: node for node in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(node, ast.ClassDef)}
        for name in ("DebSocBritishParliamentaryPreferences", "DebSocAsianParliamentaryPreferences"):
            values = {node.targets[0].id: ast.literal_eval(node.value) for node in classes[name].body
                      if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                      and isinstance(node.value, ast.Constant)}
            self.assertEqual(values["data_entry__participant_ballots"], "private-urls")
            self.assertEqual(values["data_entry__participant_feedback"], "private-urls")
            if name.startswith("DebSocAsian"):
                self.assertTrue(values["data_entry__individual_ballots"])
                self.assertEqual(values["debate_rules__ballots_per_debate_prelim"], "per-adj")


if __name__ == "__main__":
    unittest.main()
