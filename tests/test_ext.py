"""zinro_ext(Chrome 拡張)の単体テストを、python -m unittest から流す。Node がなければ飛ばす。

E2E(実際の拡張を Chromium で動かす)は、Playwright と数分が要るので、ここには含めない
(zinro_ext/README.md の「テスト」を参照)。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "zinro_ext"


@unittest.skipUnless(shutil.which("node"), "node がない")
class ExtUnitTests(unittest.TestCase):
    def test_node_unit_tests(self):
        files = sorted(str(p) for p in (EXT / "tests").glob("*.test.js"))
        self.assertTrue(files, "単体テストが見つからない")
        r = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, (r.stdout[-3000:] + r.stderr[-1500:]))


class ExtManifestTests(unittest.TestCase):
    """Node がなくても確かめられる、最小の前提。"""

    def test_manifest_has_no_network_permissions(self):
        m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["manifest_version"], 3)
        self.assertEqual(m["permissions"], ["storage"])
        self.assertNotIn("host_permissions", m)
        self.assertNotIn("background", m)


if __name__ == "__main__":
    unittest.main()
