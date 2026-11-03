from __future__ import annotations

import json
import unittest

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import config


class ConfigTest(TempDirCase):
    def test_defaults(self):
        cfg = config.load(self.fake_brain())
        self.assertEqual((cfg.role, cfg.max_file_kb, cfg.stale_after_days, cfg.python, cfg.packages, cfg.gates),
                         ("brain", 1024, 180, "python3", "stdlib-only", []))
        self.assertEqual((cfg.gates_off, cfg.gate_exempt, cfg.deny_patterns, cfg.large_file_allow),
                         ([], [], [], []))
        self.assertEqual((cfg.template_source, cfg.template_version, cfg.private_file_expected,
                          cfg.private_patterns), (None, None, False, []))

    def test_explicit_values_are_read(self):
        extra = {
            "template": {"source": "/src", "version": "0.1.0+abcdef1"},
            "scripts": {"python": ".venv/bin/python", "packages": "allowed"},
            "privacy": {"deny_patterns": ["10\\.1\\."], "max_file_kb": 64, "large_file_allow": ["data/"],
                        "private_file_expected": True},
            "practices": {"stale_after_days": 30},
            "gates": [{"paths": ["a/**"], "skill": "lab-x", "reason": "r"}],
            "gates_off": [{"id": "g", "reason": "r"}],
            "gate_exempt": ["archive/**"],
        }
        root = self.fake_brain(prefix="se2", role="template", extra=extra)
        cfg = config.load(root)
        self.assertEqual((cfg.root, cfg.prefix, cfg.role, cfg.description), (root, "se2", "template", "A brain for tests"))
        self.assertEqual((cfg.template_source, cfg.template_version), ("/src", "0.1.0+abcdef1"))
        self.assertEqual((cfg.python, cfg.packages), (".venv/bin/python", "allowed"))
        self.assertEqual((cfg.deny_patterns, cfg.max_file_kb, cfg.large_file_allow, cfg.private_file_expected),
                         (["10\\.1\\."], 64, ["data/"], True))
        self.assertEqual(cfg.stale_after_days, 30)
        self.assertEqual((cfg.gates, cfg.gates_off, cfg.gate_exempt),
                         (extra["gates"], extra["gates_off"], ["archive/**"]))
        self.assertEqual(cfg.raw["prefix"], "se2")

    def test_private_patterns(self):
        root = self.fake_brain()
        (root / ".brain-private").write_text("castle-black\n# note\n\n", encoding="utf-8")
        self.assertEqual(config.load(root).private_patterns, ["castle-black"])

    def test_missing_private_file_means_no_patterns(self):
        self.assertEqual(config.load(self.fake_brain()).private_patterns, [])

    def test_unreadable_private_file_is_a_config_error(self):
        # An unreadable .brain-private must not silently become "no private patterns".
        root = self.fake_brain()
        (root / ".brain-private").mkdir()
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(root)
        self.assertIn(".brain-private", str(ctx.exception))

    def test_local_json_overrides_source(self):
        root = self.fake_brain(extra={"template": {"source": "/from/brain.json", "version": "0.1.0"}})
        self.assertEqual(config.effective_source(config.load(root)), "/from/brain.json")
        (root / "brain.local.json").write_text(json.dumps({"template": {"source": "/x"}}), encoding="utf-8")
        self.assertEqual(config.effective_source(config.load(root)), "/x")

    def test_effective_source_without_any_source_is_none(self):
        self.assertIsNone(config.effective_source(config.load(self.fake_brain())))

    def test_malformed_local_json_is_a_config_error(self):
        root = self.fake_brain()
        (root / "brain.local.json").write_text("{nope", encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.effective_source(config.load(root))

    def test_prefix_validation(self):
        self.assertIsNone(config.validate_prefix("lab"))
        for bad in ("brain", "template", "Lab", "l", "x" * 17, "9ab", "la-b", "lab\n", ""):
            self.assertIsNotNone(config.validate_prefix(bad), bad)
        self.assertIsNone(config.validate_prefix("x" * 16))

    def test_missing_brain_json(self):
        with self.assertRaises(config.ConfigError):
            config.load(self.tmp)

    def test_invalid_brain_json(self):
        root = self.fake_brain()
        for text in ("{nope", "[]", '{"role": "king"}', '{"privacy": []}', '{"privacy": {"max_file_kb": "big"}}',
                     '{"privacy": {"max_file_kb": true}}', '{"gate_exempt": "archive"}', '{"gates": ["x"]}',
                     '{"scripts": {"packages": "pip"}}'):
            with self.subTest(text=text):
                (root / "brain.json").write_text(text, encoding="utf-8")
                with self.assertRaises(config.ConfigError):
                    config.load(root)

    def test_write_raw_keeps_key_order_and_ends_with_newline(self):
        root = self.fake_brain()
        raw = {"zeta": 1, "name": "n — dash", "alpha": {"b": [1, 2], "a": None}}
        config.write_raw(root, raw)
        text = (root / "brain.json").read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        self.assertTrue(text.startswith('{\n  "zeta": 1,'))
        self.assertEqual(config.read_raw(root), raw)


if __name__ == "__main__":
    unittest.main()
