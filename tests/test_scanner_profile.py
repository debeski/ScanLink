import json
import os
import tempfile
import unittest
from unittest.mock import patch

import scanner
import utils


class FakeTwain:
    ICAP_XRESOLUTION = 1
    ICAP_YRESOLUTION = 2
    CAP_FEEDERENABLED = 3
    CAP_AUTOFEED = 4
    CAP_DUPLEXENABLED = 5
    ICAP_PIXELTYPE = 6
    ICAP_BITDEPTH = 7
    CAP_PAPERPROTECTION = 8
    CAP_INDICATORS = 9
    CAP_XFERCOUNT = 10

    TWTY_FIX32 = 100
    TWTY_BOOL = 101
    TWTY_INT16 = 102
    TWTY_UINT16 = 103

    TWPT_BW = 200
    TWPT_GRAY = 201
    TWPT_RGB = 202


class FakeSource:
    def __init__(self):
        self.calls = []

    def set_capability(self, capability, type_id, value):
        self.calls.append((capability, type_id, value))


class ScannerProfileTests(unittest.TestCase):
    def test_missing_config_uses_archive_safe_profile_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            with patch.object(utils, "CONFIG_FILE", config_file):
                config = utils.load_config()

        self.assertEqual(config["scan_profile_version"], 1)
        self.assertEqual(config["resolution"], 200)
        self.assertEqual(config["scan_source"], "adf")
        self.assertEqual(config["scan_side"], "front")
        self.assertEqual(config["color_mode"], "color")
        self.assertFalse(config["paper_protection"])

    def test_legacy_config_is_migrated_to_archive_safe_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            with open(config_file, "w", encoding="utf-8") as config_handle:
                json.dump({"resolution": 300, "paper_protection": True}, config_handle)

            with patch.object(utils, "CONFIG_FILE", config_file):
                config = utils.load_config()

        self.assertEqual(config["resolution"], 200)
        self.assertEqual(config["scan_source"], "adf")
        self.assertEqual(config["scan_side"], "front")
        self.assertEqual(config["color_mode"], "color")
        self.assertFalse(config["paper_protection"])

    def test_versioned_config_preserves_operator_profile_choices(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            with open(config_file, "w", encoding="utf-8") as config_handle:
                json.dump(
                    {
                        "scan_profile_version": 1,
                        "resolution": 300,
                        "scan_source": "flatbed",
                        "scan_side": "front_back",
                        "color_mode": "grayscale",
                        "paper_protection": True,
                    },
                    config_handle,
                )

            with patch.object(utils, "CONFIG_FILE", config_file):
                config = utils.load_config()

        self.assertEqual(config["resolution"], 300)
        self.assertEqual(config["scan_source"], "flatbed")
        self.assertEqual(config["scan_side"], "front_back")
        self.assertEqual(config["color_mode"], "grayscale")
        self.assertTrue(config["paper_protection"])

    def test_default_profile_configures_adf_front_color_and_paper_protection_off(self):
        source = FakeSource()
        manager = scanner.ScannerManager()
        config = {
            "resolution": 200,
            "scan_source": "adf",
            "scan_side": "front",
            "color_mode": "color",
            "paper_protection": False,
        }

        with patch.object(scanner, "twain", FakeTwain):
            manager._configure_source(source, config, show_ui=False)

        self.assertIn((FakeTwain.ICAP_XRESOLUTION, FakeTwain.TWTY_FIX32, 200.0), source.calls)
        self.assertIn((FakeTwain.ICAP_YRESOLUTION, FakeTwain.TWTY_FIX32, 200.0), source.calls)
        self.assertIn((FakeTwain.CAP_FEEDERENABLED, FakeTwain.TWTY_BOOL, True), source.calls)
        self.assertIn((FakeTwain.CAP_AUTOFEED, FakeTwain.TWTY_BOOL, True), source.calls)
        self.assertIn((FakeTwain.CAP_DUPLEXENABLED, FakeTwain.TWTY_BOOL, False), source.calls)
        self.assertIn((FakeTwain.ICAP_PIXELTYPE, FakeTwain.TWTY_UINT16, FakeTwain.TWPT_RGB), source.calls)
        self.assertIn((FakeTwain.CAP_PAPERPROTECTION, FakeTwain.TWTY_BOOL, False), source.calls)
        self.assertIn((FakeTwain.CAP_INDICATORS, FakeTwain.TWTY_BOOL, False), source.calls)
        self.assertIn((FakeTwain.CAP_XFERCOUNT, FakeTwain.TWTY_INT16, -1), source.calls)

    def test_flatbed_duplex_grayscale_profile_changes_capabilities(self):
        source = FakeSource()
        manager = scanner.ScannerManager()
        config = {
            "resolution": 240,
            "scan_source": "flatbed",
            "scan_side": "front_back",
            "color_mode": "grayscale",
            "paper_protection": True,
        }

        with patch.object(scanner, "twain", FakeTwain):
            manager._configure_source(source, config, show_ui=False)

        self.assertIn((FakeTwain.CAP_FEEDERENABLED, FakeTwain.TWTY_BOOL, False), source.calls)
        self.assertIn((FakeTwain.CAP_AUTOFEED, FakeTwain.TWTY_BOOL, False), source.calls)
        self.assertIn((FakeTwain.CAP_DUPLEXENABLED, FakeTwain.TWTY_BOOL, True), source.calls)
        self.assertIn((FakeTwain.ICAP_PIXELTYPE, FakeTwain.TWTY_UINT16, FakeTwain.TWPT_GRAY), source.calls)
        self.assertIn((FakeTwain.ICAP_BITDEPTH, FakeTwain.TWTY_UINT16, 8), source.calls)
        self.assertIn((FakeTwain.CAP_PAPERPROTECTION, FakeTwain.TWTY_BOOL, True), source.calls)


if __name__ == "__main__":
    unittest.main()
