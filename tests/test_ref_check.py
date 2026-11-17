#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""liblp 解析 / 参考基线比对的无 ROM 回归测试

运行：
    python tests/test_ref_check.py
    python -m unittest discover -s tests -v

覆盖：
  * 合成 super.img（geometry + 标准头 + 4 张表）能被 parse_super 正确读出
  * 头部描述符基址后移（+80，参考包的那种）也能识别
  * compare_super：分区缺失 / 超预算 / 多出 _b 都能判到 fail
  * 刷机脚本混排编码时 merge_versions 仍能取到干净字段
  * emit_reference 生成的基线可以原样回灌给 compare_package
  * 有真实基线 + 真实成品包时（设置 XMAPORT_REF_PACKAGE）做一次端到端比对
"""

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import ref_check as rc  # noqa: E402

MiB = 1024 * 1024
SECTOR = 512

# 参考包实测的那 8 个分区（真实扇区数），单元测试里等比缩小 128 倍，
# 这样 super 只要 64 MiB 就能覆盖「分区合计 < 容量」的正常分支。
REAL_SPEC = [
    ("mi_ext_a", 207336),
    ("odm_a", 4504688),
    ("vendor_a", 916080),
    ("vendor_dlkm_a", 60208),
    ("system_a", 1862152),
    ("system_dlkm_a", 29168),
    ("product_a", 6073936),
    ("system_ext_a", 1781600),
]
SCALE = 128
SPEC = [(name, max(8, sectors // SCALE)) for name, sectors in REAL_SPEC]
SPEC_MAP = dict(SPEC)
GROUP = "qti_dynamic_partitions_a"
SUPER_SIZE = 64 * MiB


def build_super(path, spec=SPEC, group_max=SUPER_SIZE, super_size=SUPER_SIZE,
                desc_base=24, extra_group=True, suffix_b=False, magic_layout="std"):
    """写一个最小可用的 liblp 镜像（不写分区数据，只写元数据）。"""
    names = [(n + ("_b" if suffix_b else ""), s) for n, s in spec]
    groups = [("default", 0)] + ([(GROUP, group_max)] if extra_group else [])
    gidx = 1 if extra_group else 0

    # ---- 表
    t_ext = b""
    first = []
    cursor = 2048
    for name, sectors in names:
        first.append(cursor)
        t_ext += struct.pack("<QIQI", sectors, 0, cursor, 0)
        cursor += sectors
    t_part = b""
    for i, (name, sectors) in enumerate(names):
        raw = name.encode()
        t_part += struct.pack("<36sIIII", raw, 1, i, 1, gidx)
    t_grp = b"".join(struct.pack("<36sIQ", g.encode(), 0, mx) for g, mx in groups)
    t_bdev = struct.pack("<QIIQ36sI", 2048, 1 << 20, 0, super_size, b"super", 0)

    def pad(b, align=8):
        return b + b"\x00" * ((align - len(b) % align) % align)

    t_part = pad(t_part)
    t_ext = pad(t_ext)
    t_grp = pad(t_grp)
    t_bdev = pad(t_bdev)
    tables = t_part + t_ext + t_grp + t_bdev
    off_part, off_ext = 0, len(t_part)
    off_grp = off_ext + len(t_ext)
    off_bdev = off_grp + len(t_grp)

    # ---- 头
    hsize = 256
    hdr = bytearray(hsize)
    struct.pack_into("<IHHII", hdr, 0, 0x414C5030, 10, 2, hsize, 0x12345678)
    for i, (o, n, s) in enumerate(((off_part, len(names), 52),
                                   (off_ext, len(names), 24),
                                   (off_grp, len(groups), 48),
                                   (off_bdev, 1, 64))):
        struct.pack_into("<III", hdr, desc_base + i * 12, o, n, s)
    struct.pack_into("<I", hdr, desc_base + 48, 1)          # virtual_ab_device

    # ---- geometry（含参考包那种扩展字段：struct_size=52）
    geo = bytearray(4096)
    struct.pack_into("<II", geo, 0, 0x616C4467, 52)
    struct.pack_into("<III", geo, 40, 65536, 3, 4096)

    if magic_layout == "backup_geometry":
        head = b"\x00" * 4096 + bytes(geo) + bytes(geo) + bytes(hdr) + tables
    else:
        head = b"\x00" * 4096 + bytes(geo) + bytes(hdr) + tables
    head += b"\x00" * (max(0, 1 * MiB - len(head)))

    path = Path(path)
    path.write_bytes(head)
    with path.open("r+b") as fh:                            # 用截断代替真写 8 GB
        fh.truncate(super_size)
    return path


def reference_from(actual):
    """把解析结果转成 compare_super 需要的基线形状。"""
    return {
        k: actual.get(k) for k in (
            "file_size", "metadata_version", "metadata_slots", "metadata_max_size",
            "logical_block_size", "flags", "groups", "partition_total",
            "super_capacity", "free_bytes", "partitions")
    }


class ParseSuper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refcheck_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_standard_header(self):
        img = build_super(self.tmp / "super.img", super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        info = rc.parse_super(img)
        self.assertTrue(info["ok"], info.get("error"))
        self.assertEqual(info["metadata_version"], "10.2")
        self.assertEqual(info["metadata_slots"], 3)
        self.assertEqual(info["logical_block_size"], 4096)
        self.assertEqual(info["flags"], ["virtual_ab_device"])
        self.assertEqual([p["name"] for p in info["partitions"]],
                         sorted(n for n, _ in SPEC))
        by_name = {p["name"]: p for p in info["partitions"]}
        self.assertEqual(by_name["product_a"]["size"], SPEC_MAP["product_a"] * SECTOR)
        self.assertEqual(by_name["product_a"]["group"], GROUP)
        self.assertEqual(info["super_capacity"], SUPER_SIZE)

    def test_descriptor_base_shifted(self):
        """参考包的头部在 +80 放描述符（前面多 64 字节摘要）。"""
        img = build_super(self.tmp / "shifted.img", desc_base=80,
                          super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        info = rc.parse_super(img)
        self.assertTrue(info["ok"], info.get("error"))
        self.assertEqual(info["header"]["desc_base"], 80)
        self.assertEqual(len(info["partitions"]), len(SPEC))

    def test_backup_geometry_layout(self):
        """magic 不在 8192 而在 12288 的镜像（参考包就是这种）。"""
        img = build_super(self.tmp / "backup.img", magic_layout="backup_geometry",
                          super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        info = rc.parse_super(img)
        self.assertTrue(info["ok"], info.get("error"))
        self.assertEqual(info["header"]["offset"], 12288)

    def test_not_lp(self):
        bad = self.tmp / "raw.img"
        bad.write_bytes(b"\x00" * (1 * MiB))
        info = rc.parse_super(bad)
        self.assertFalse(info["ok"])
        self.assertIn("liblp", info["error"])

    def test_sparse_rejected(self):
        sp = self.tmp / "sparse.img"
        sp.write_bytes(b"\x3a\xff\x26\xed" + b"\x00" * 100)
        info = rc.parse_super(sp)
        self.assertFalse(info["ok"])
        self.assertIn("sparse", info["error"])


class CompareSuper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refcmp_"))
        self.ref_img = build_super(self.tmp / "ref.img", super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        self.ref = reference_from(rc.parse_super(self.ref_img))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def levels(self, findings):
        return [f["level"] for f in findings], [f["msg"] for f in findings]

    def test_same_layout_passes(self):
        findings = rc.compare_super(rc.parse_super(self.ref_img), self.ref)
        levels, _ = self.levels(findings)
        self.assertNotIn("fail", levels)

    def test_missing_partition_fails(self):
        img = build_super(self.tmp / "short.img", spec=SPEC[:-1],
                          super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        findings = rc.compare_super(rc.parse_super(img), self.ref)
        levels, msgs = self.levels(findings)
        self.assertIn("fail", levels)
        self.assertTrue(any("缺少分区 system_ext_a" in m for m in msgs), msgs)

    def test_slot_b_fails(self):
        img = build_super(self.tmp / "slotb.img", suffix_b=True,
                          super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        findings = rc.compare_super(rc.parse_super(img), self.ref)
        levels, msgs = self.levels(findings)
        self.assertIn("fail", levels)
        self.assertTrue(any("_b" in m for m in msgs), msgs)

    def test_over_budget_fails(self):
        bigger = [(n, s * 2) for n, s in SPEC]
        img = build_super(self.tmp / "big.img", spec=bigger,
                          super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        findings = rc.compare_super(rc.parse_super(img), self.ref)
        levels, msgs = self.levels(findings)
        self.assertIn("fail", levels)
        self.assertTrue(any("大于基线" in m or "分区总和大盘" in m for m in msgs), msgs)

    def test_wrong_group_fails(self):
        img = build_super(self.tmp / "nogroup.img", extra_group=False,
                          super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        findings = rc.compare_super(rc.parse_super(img), self.ref)
        levels, msgs = self.levels(findings)
        self.assertIn("fail", levels)
        self.assertTrue(any(GROUP in m for m in msgs), msgs)


class Versions(unittest.TestCase):
    def test_merge_mixed_encoding(self):
        """刷机脚本 UTF-8 与 ANSI 混排时，仍取到干净字段。"""
        tmp = Path(tempfile.mkdtemp(prefix="refver_"))
        bat = tmp / "Flash.bat"
        raw = ("echo.机型代号:SHENNONG\r\n"
               "echo.移植版本:OS4.0.7.0.XPACNXM\r\n").encode("utf-8")
        raw += b"echo.\xd6\xd0\xce\xc4\r\n"          # 一段 GBK 中文，破坏单一编码
        bat.write_bytes(raw)
        variants = rc._text_variants(bat)
        merged = rc.merge_versions(variants)
        self.assertEqual(merged["device_code"], "SHENNONG")
        self.assertEqual(merged["donor_version"], "OS4.0.7.0.XPACNXM")

    def test_version_tags(self):
        info = rc.parse_versions("底包版本: OS3.0.310.0.WNBCNXM\n移植版本: OS4.0.7.0.XPACNXM")
        self.assertEqual(info["base_version"], "OS3.0.310.0.WNBCNXM")
        self.assertIn("OS3.0.310.0.WNBCNXM", info["version_tags"])


class EmitAndPackage(unittest.TestCase):
    """emit → compare_package 的闭环（用合成卡刷包，不需要 ROM）"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="refemit_"))
        root = self.tmp / "pkg"
        (root / "images").mkdir(parents=True)
        build_super(root / "images" / "super.img", super_size=SUPER_SIZE, group_max=SUPER_SIZE)
        for name in rc.REQUIRED_IMAGES:
            (root / "images" / name).write_bytes(b"\x00" * 1024)
        (root / "META-INF" / "com" / "google" / "android").mkdir(parents=True)
        (root / "META-INF" / "com" / "google" / "android" / "update-binary").write_text(
            "机型代号:SHENNONG\n机型名称:Xiaomi 14 Pro\n"
            "底包版本:OS3.0.310.0.WNBCNXM\n移植机型:Xiaomi 17 Ultra\n"
            "移植版本:OS4.0.7.0.XPACNXM\n", encoding="utf-8")
        (root / "Flash.bat").write_text("echo hi\n", encoding="utf-8")
        (root / "bin" / "android").mkdir(parents=True)
        for f in ("7zzs", "zstd"):
            (root / "bin" / "android" / f).write_bytes(b"")
        self.root = root

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_emit_then_compare(self):
        ref = rc.emit_reference(self.root)
        self.assertEqual(ref["versions"]["device_code"], "SHENNONG")
        self.assertEqual(len(ref["super"]["partitions"]), len(SPEC))
        self.assertEqual(ref["budget"], SUPER_SIZE)

        findings = rc.compare_super(rc.parse_super(self.root / "images" / "super.img"),
                                    ref["super"])
        self.assertNotIn("fail", [f["level"] for f in findings])

        # 版本写错 -> compare_package 判 fail
        ref["versions"]["device_code"] = "MADRID"
        findings = rc.compare_package(
            {"versions": {"device_code": "SHENNONG", "device_name": "Xiaomi 14 Pro",
                          "base_version": "OS3.0.310.0.WNBCNXM"}}, ref)
        self.assertIn("fail", [f["level"] for f in findings])

    def test_audit_package_flags_missing_required(self):
        (self.root / "images" / "vbmeta.img").unlink()
        pkg = rc.audit_package(self.root)
        fails = [f["msg"] for f in pkg["findings"] if f["level"] == "fail"]
        self.assertTrue(any("vbmeta" in m for m in fails), fails)
        self.assertFalse(pkg["ok"])


class RealPackage(unittest.TestCase):
    """有真实成品包时（XMAPORT_REF_PACKAGE=路径）做一次端到端比对。"""

    def test_real_reference(self):
        pkg_dir = os.environ.get("XMAPORT_REF_PACKAGE", "D:\\Rom6")
        ref_path = ROOT / "reference" / "rom6_reference.json"
        if not (Path(pkg_dir).is_dir() and ref_path.is_file()):
            self.skipTest("没有真实成品包或基线，跳过")
        ref = rc.load_reference(ref_path)
        info = rc.parse_super(Path(pkg_dir) / "images" / "super.img")
        self.assertTrue(info["ok"], info.get("error"))
        findings = rc.compare_super(info, ref["super"])
        self.assertNotIn("fail", [f["level"] for f in findings])
        self.assertEqual(info["super_capacity"], ref["super"]["super_capacity"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
