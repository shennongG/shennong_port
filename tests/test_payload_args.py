#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""payload 解包参数 / 超时的单元测试（不需要真实 payload.bin）

    python tests/test_payload_args.py
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("xm", str(ROOT / "XMAPort.py"))
xm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xm)


class PayloadArgs(unittest.TestCase):
    def test_partitions_and_concurrency(self):
        captured = {}

        def fake_run(cmd, timeout=None, **kwargs):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return subprocess.CompletedProcess(cmd, 0)

        tmp = Path(tempfile.mkdtemp())
        rom = tmp / "rom"
        out = tmp / "out"
        rom.mkdir()
        (rom / "payload.bin").write_bytes(b"\x00" * 64)
        old = xm.run_tool
        xm.run_tool = fake_run
        try:
            rc = xm.extract_payload_bin(rom, out,
                                        partitions=["system", "system_ext", "product"],
                                        timeout=3600, concurrency=8)
        finally:
            xm.run_tool = old
        self.assertEqual(rc, 0)
        self.assertEqual(captured["timeout"], 3600)
        cmd = captured["cmd"]
        self.assertIn("-p", cmd)
        self.assertIn("system,system_ext,product", cmd)
        self.assertIn("-c", cmd)
        self.assertIn("8", cmd)

    def test_check_subset(self):
        tmp = Path(tempfile.mkdtemp())
        for n in ("system.img", "product.img"):
            (tmp / n).write_bytes(b"x")
        self.assertTrue(xm.check_payload_extracted(tmp, required=["system.img", "product.img"]))
        self.assertFalse(xm.check_payload_extracted(tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
