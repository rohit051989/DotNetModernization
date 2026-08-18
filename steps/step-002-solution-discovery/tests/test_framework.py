import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discovery import framework


class NormalizeOneTests(unittest.TestCase):
    def test_legacy_dotted(self):
        self.assertEqual(framework.normalize_one("v4.7.2"), ("net-framework", "4.7.2", None))
        self.assertEqual(framework.normalize_one("v4.8"), ("net-framework", "4.8", None))

    def test_legacy_short_moniker(self):
        self.assertEqual(framework.normalize_one("net47"), ("net-framework", "4.7", None))
        self.assertEqual(framework.normalize_one("net472"), ("net-framework", "4.7.2", None))
        self.assertEqual(framework.normalize_one("net48"), ("net-framework", "4.8", None))

    def test_netcoreapp(self):
        self.assertEqual(framework.normalize_one("netcoreapp2.1"), ("net-core", "2.1", None))
        self.assertEqual(framework.normalize_one("netcoreapp3.1"), ("net-core", "3.1", None))

    def test_netstandard(self):
        self.assertEqual(framework.normalize_one("netstandard2.0"), ("net-standard", "2.0", None))

    def test_net_modern(self):
        self.assertEqual(framework.normalize_one("net6.0"), ("net", "6.0", None))
        self.assertEqual(framework.normalize_one("net10.0"), ("net", "10.0", None))

    def test_net_modern_platform_suffix(self):
        self.assertEqual(framework.normalize_one("net6.0-windows"), ("net", "6.0", "windows"))

    def test_unknown(self):
        self.assertEqual(framework.normalize_one("banana"), ("unknown", None, None))
        self.assertEqual(framework.normalize_one(""), ("unknown", None, None))


class ResolveTests(unittest.TestCase):
    def test_single_target_no_warning(self):
        family, version, is_multi, warning = framework.resolve(["net472"])
        self.assertEqual((family, version, is_multi), ("net-framework", "4.7.2", False))
        self.assertIsNone(warning)

    def test_platform_suffix_warns(self):
        _family, _version, _is_multi, warning = framework.resolve(["net6.0-windows"])
        self.assertIn("platform suffix", warning)

    def test_multi_targeting_picks_highest_and_warns(self):
        family, version, is_multi, warning = framework.resolve(["net472", "net6.0"])
        self.assertEqual((family, version, is_multi), ("net", "6.0", True))
        self.assertIn("multi-targeting", warning)

    def test_multi_targeting_within_same_family_picks_highest_version(self):
        family, version, _is_multi, _warning = framework.resolve(["netstandard2.0", "netstandard2.1"])
        self.assertEqual((family, version), ("net-standard", "2.1"))


if __name__ == "__main__":
    unittest.main()
