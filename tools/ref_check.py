#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考包比对 / super.img 布局审计（纯标准库，不依赖 lpdumps.exe）

为什么要有这个模块
------------------
`D:\\Rom6`（X-MiPort_Mi14Pro_OS4.0.7.0.XPACNXM_nezha_*.zip）是「小米 17 Ultra
(`nezha`) → 小米 14 Pro (`shennong`)」这条路线**已经实机验证过**的成品包：
它的 super.img 布局（只有 `_a`、单 group、virtual-A/B、8 329 000 000 量级）
就是本项目的验收基线。以前的流水线只在注释里写「对齐参考包」，错了要等刷机
才发现；现在把基线变成 JSON，打包前后各跑一次就能拦住：

  * 布局不对（多了 `_b`、group 名不同、virtual_ab 没打开）
  * 预算不对（super 比真机分区大，或者小到装不下）
  * 分区缺失/尺寸异常（odm/vendor 拿错底包、system 精简过头）
  * 卡刷包不完整（缺 vbmeta / update-binary / ROOT 组件 / 刷机脚本）

解析器是「容错」实现：liblp 几何体与元数据头的偏移在不同厂商镜像上不完全一样
（参考包的元数据头就不在标准的 8192，而在 12288），所以按 magic 扫描 + 结构
校验的方式定位，而不是写死偏移。

用法
----
::

    python tools\\ref_check.py package D:\\Rom6                  # 审计成品包
    python tools\\ref_check.py package D:\\Rom6 --emit ref.json  # 用成品包生成基线
    python tools\\ref_check.py super workspace\\packed\\super.img  # 只比对 super 布局
    python tools\\ref_check.py all workspace\\output               # 包 + 里面的 super

    --ref  指定基线（默认 reference/rom6_reference.json）
    --json 机器可读输出（CI / 脚本用）
    --tolerance-mib N  尺寸比较的宽容值，默认 64
    --strict  warn 也算失败（默认只有 fail 让退出码变成 1）

退出码：0 = 通过（允许 warn），1 = 有 fail，2 = 参数/IO 错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REF = ROOT / "reference" / "rom6_reference.json"

MiB = 1024 * 1024

# ---------------------------------------------------------------- liblp 常量
LP_HEADER_MAGIC = b"0PLA"          # 0x414C5030
LP_GEOMETRY_MAGIC = b"gDla"        # 0x616c4467
LP_PARTITION_RESERVED_BYTES = 4096
LP_METADATA_GEOMETRY_SIZE = 4096
SCAN_BYTES = 4 * MiB               # 元数据一定在前几 MB 内

EXTENT_TYPE = {0: "linear", 1: "zero"}
HEADER_FLAGS = {1: "virtual_ab_device"}
GROUP_FLAGS = {1: "sparse"}
PARTITION_ATTRS = {
    1 << 0: "readonly",
    1 << 1: "slot_suffixed",
    1 << 2: "updated",
    1 << 3: "disabled",
}

# 14 Pro 卡刷包里必须存在的镜像（缺了刷不进/开不了机）
REQUIRED_IMAGES = [
    "boot.img",
    "init_boot_official.img",
    "vendor_boot.img",
    "vbmeta.img",
    "vbmeta_system.img",
]
OPTIONAL_IMAGES = ["recovery_twrp.img", "dtbo.img", "modem.img", "modemfirmware.img"]


# ================================================================ 小工具
def human(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0 or unit == "TiB":
            return "{:.2f} {}".format(n, unit) if unit != "B" else "{:.0f} B".format(n)
        n /= 1024.0
    return "{:.2f} TiB".format(n)


def _flag_names(value: int, table: dict) -> list:
    return [name for bit, name in table.items() if value & bit]


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()


def _is_printable_name(name: str) -> bool:
    return bool(name) and all(32 < ord(ch) < 127 for ch in name)


# ================================================================ super 解析
def _find_header(buf: bytes) -> list:
    """返回所有 `0PLA` magic 的偏移（元数据头不在固定位置时用）。"""
    hits, start = [], 0
    while True:
        i = buf.find(LP_HEADER_MAGIC, start)
        if i < 0:
            return hits
        hits.append(i)
        start = i + 1


# LpMetadataPartition / LpMetadataExtent / LpMetadataPartitionGroup /
# LpMetadataBlockDevice 的序列化长度是 ABI 常量，用来验证「描述符基址」猜对了没有。
ENTRY_SIZES = {"partitions": 52, "extents": 24, "groups": 48, "block_devices": 64}
# 标准头从 +24 开始放 4 个描述符；部分厂商镜像（含参考包）在 header 里多塞了
# 64 字节摘要（SHA-256），描述符整体后移到 +80。都试一遍，用 ABI 长度校验。
DESC_BASES = (24, 80, 76, 88, 92)


def _desc_at(buf: bytes, off: int, base: int) -> dict:
    descs = {}
    for i, key in enumerate(("partitions", "extents", "groups", "block_devices")):
        d_off, d_num, d_size = struct.unpack_from("<III", buf, off + base + i * 12)
        descs[key] = {"offset": d_off, "num": d_num, "size": d_size}
    return descs


def _descs_valid(descs: dict) -> bool:
    names = ("partitions", "extents", "groups", "block_devices")
    for key in names:
        d = descs[key]
        if d["size"] != ENTRY_SIZES[key]:
            return False
    if descs["partitions"]["offset"] != 0 or descs["partitions"]["num"] <= 0:
        return False
    if descs["partitions"]["num"] > 256 or descs["extents"]["num"] > 4096:
        return False
    if not (1 <= descs["groups"]["num"] <= 64 and 1 <= descs["block_devices"]["num"] <= 8):
        return False
    offsets = [descs[k]["offset"] for k in names]
    if offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
        return False
    # 最后一张表必须落在 header 后面第一兆内
    last = descs["block_devices"]
    return last["offset"] + last["num"] * last["size"] <= 8 * MiB


def _parse_header_at(buf: bytes, off: int) -> dict | None:
    """尝试把 off 处的字节解释成 LpMetadataHeader；不合法返回 None。"""
    if off + 128 > len(buf):
        return None
    if buf[off:off + 4] != LP_HEADER_MAGIC:
        return None
    vmaj, vmin, hsize, hck = struct.unpack_from("<HHII", buf, off + 4)
    if not (9 <= vmaj <= 12) or hsize not in (80, 84, 128, 256, 512):
        return None
    for base in DESC_BASES:
        if off + base + 48 + 4 > len(buf):
            continue
        descs = _desc_at(buf, off, base)
        if not _descs_valid(descs):
            continue
        flags = struct.unpack_from("<I", buf, off + base + 48)[0]
        tables_size = sum(d["num"] * d["size"] for d in descs.values())
        return {
            "offset": off,
            "version": "{}.{}".format(vmaj, vmin),
            "header_size": hsize,
            "header_checksum": hck,
            "desc_base": base,
            "descs": descs,
            "tables_size": tables_size,
            "flags_raw": flags,
        }
    return None


def _parse_geometry(buf: bytes) -> dict:
    """geometry 在主元数据块之前；结构尾部多了几个字段（struct_size=52）也能读。"""
    i = buf.find(LP_GEOMETRY_MAGIC)
    if i < 0:
        return {}
    struct_size = struct.unpack_from("<I", buf, i + 4)[0]
    # metadata_max_size / slot_count / lbs 固定在 +40/+44/+48（含 struct_size=52 的扩展布局）
    geo = {"offset": i, "struct_size": struct_size}
    if i + 52 <= len(buf):
        mx, slots, lbs = struct.unpack_from("<III", buf, i + 40)
        if 4096 <= mx <= 1 << 24 and 1 <= slots <= 4 and lbs in (512, 4096, 0):
            geo.update(metadata_max_size=mx, metadata_slots=slots, logical_block_size=lbs)
    return geo


def parse_super(path, scan_bytes: int = SCAN_BYTES) -> dict:
    """解析 super.img / 分区镜像里的 liblp 元数据。"""
    path = Path(path)
    out = {"path": str(path), "file_size": 0, "ok": False, "error": ""}
    with path.open("rb") as fh:
        head = fh.read(scan_bytes)
        fh.seek(0, os.SEEK_END)
        out["file_size"] = fh.tell()

    if head[:4] == b"\x3a\xff\x26\xed":       # sparse
        out["error"] = "sparse 格式：请先 simg2img 再解析"
        return out
    if LP_HEADER_MAGIC not in head:
        out["error"] = "没有 liblp 元数据（不是 super.img，或者被压缩过）"
        return out

    out["geometry"] = _parse_geometry(head)
    hdr = None
    for off in _find_header(head):
        cand = _parse_header_at(head, off)
        if not cand:
            continue
        hdr = cand
        break
    if not hdr:
        out["error"] = "找到 magic 但元数据头结构不合法"
        return out
    out["header"] = hdr

    tables_at = hdr["offset"] + hdr["header_size"]
    need = tables_at + hdr["tables_size"]
    if need > len(head):                        # 元数据比扫描窗口还靠后，补读一次
        with path.open("rb") as fh:
            fh.seek(tables_at)
            head = head[:tables_at] + fh.read(need - tables_at)
    tables = head[tables_at:]
    d = hdr["descs"]
    bad = []                                    # 元数据里出现离谱数值时不下结论

    def rows(key, fmt):
        off, num, size = d[key]["offset"], d[key]["num"], d[key]["size"]
        if off + num * size > len(tables):
            bad.append("{} 表越界（offset={} num={} size={}）".format(key, off, num, size))
            return []
        return [struct.unpack_from(fmt, tables, off + i * size) for i in range(num)]

    groups = []
    for name, gflags, gmax in rows("groups", "<36sIQ"):
        groups.append({"name": _cstr(name), "max_size": gmax,
                       "flags": _flag_names(gflags, GROUP_FLAGS) or ["none"]})

    bdevs = []
    for first, align, aoff, size, name, bflags in rows("block_devices", "<QIIQ36sI"):
        bdevs.append({"name": _cstr(name), "size": size,
                      "first_sector": first, "alignment": align})

    extents = []
    for num_sectors, ttype, target_data, tsource in rows("extents", "<QIQI"):
        extents.append({"num_sectors": num_sectors,
                        "type": EXTENT_TYPE.get(ttype, str(ttype)),
                        "start_sector": target_data,
                        "target_source": tsource})

    parts, problems = [], []
    for name, attrs, first_ext, num_ext, gidx in rows("partitions", "<36sIIII"):
        pname = _cstr(name)
        if not _is_printable_name(pname):
            problems.append("分区名不可打印：{!r}".format(pname))
            continue
        mine = extents[first_ext:first_ext + num_ext]
        sectors = sum(e["num_sectors"] for e in mine if e["type"] == "linear")
        parts.append({
            "name": pname,
            "group": groups[gidx]["name"] if 0 <= gidx < len(groups) else "?",
            "attrs": _flag_names(attrs, PARTITION_ATTRS),
            "size": sectors * 512,
            "sectors": sectors,
            "first_sector": mine[0]["start_sector"] if mine else 0,
            "extents": len(mine),
        })

    if not parts:
        out["error"] = "元数据里没有可解析的分区表（{}）".format("; ".join(problems) or "空")
        return out

    total = sum(p["size"] for p in parts)
    geom = out.get("geometry") or {}
    out.update({
        "ok": True,
        "metadata_version": hdr["version"],
        "metadata_slots": geom.get("metadata_slots"),
        "metadata_max_size": geom.get("metadata_max_size"),
        "logical_block_size": geom.get("logical_block_size"),
        "flags": _flag_names(hdr["flags_raw"], HEADER_FLAGS) or ["none"],
        "groups": groups,
        "block_devices": bdevs,
        "partitions": sorted(parts, key=lambda p: p["name"]),
        "partition_total": total,
        "super_capacity": bdevs[0]["size"] if bdevs else None,
        "free_bytes": (bdevs[0]["size"] - total) if bdevs else None,
        "problems": problems,
    })
    return out


# ================================================================ 卡刷包审计
VERSION_RE = re.compile(r"\bOS\d+\.\d+\.\d+\.\d+\.[A-Z]{3}CNXM\b")
DEVICE_CODE_RE = re.compile(r"(?:机型代号|Device Code)\s*[:：]\s*([A-Za-z0-9_\-]+)")
DEVICE_NAME_RE = re.compile(r"(?:机型名称|Device Name)\s*[:：]\s*([^\r\n]+)")
BASE_RE = re.compile(r"(?:底包版本|Base ROM Version)\s*[:：]\s*([^\r\n]+)")
DONOR_NAME_RE = re.compile(r"(?:移植机型|Port From)\s*[:：]\s*([^\r\n]+)")
DONOR_VER_RE = re.compile(r"(?:移植版本|Port Version)\s*[:：]\s*([^\r\n]+)")
ANDROID_RE = re.compile(r"(?:安卓版本|Android Version|Android)\s*[:：]\s*(\d+)")
DATA_RE = re.compile(r"(?:加密状态|Data State)\s*[:：]\s*([^\r\n]+)")


def _text_variants(path: Path) -> list:
    """刷机脚本经常是「UTF-8 与 ANSI 混排」，单一编码解不干净：两种都解，取最优。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    out = []
    for enc in ("utf-8", "gbk"):
        try:
            out.append(raw.decode(enc, "replace"))
        except LookupError:
            continue
    return out


def _bad_chars(text: str) -> int:
    return text.count("\ufffd")


def _pick(values: list):
    """从多个解码版本里挑一个字段值：优先没有替换符的，其次替换符最少。"""
    values = [v for v in values if v]
    if not values:
        return ""
    return sorted(values, key=lambda v: (_bad_chars(v), -len(v)))[0]


def merge_versions(variants: list) -> dict:
    """把多个解码版本的解析结果合并成一份（逐字段挑最干净的）。"""
    merged = {}
    collected = {}
    for text in variants:
        info = parse_versions(text)
        for key, value in info.items():
            if key == "version_tags":
                collected.setdefault(key, [])
                for tag in value:
                    if tag not in collected[key]:
                        collected[key].append(tag)
            else:
                collected.setdefault(key, []).append(value)
    for key, values in collected.items():
        if key == "version_tags":
            merged[key] = sorted(values)
        else:
            merged[key] = _pick(values)
    return merged


def parse_versions(text: str) -> dict:
    """从刷机脚本（bat / update-binary）里抠出机型与版本信息。"""
    info = {}
    for key, rx in (("device_code", DEVICE_CODE_RE), ("device_name", DEVICE_NAME_RE),
                    ("base_version", BASE_RE), ("donor_name", DONOR_NAME_RE),
                    ("donor_version", DONOR_VER_RE), ("android", ANDROID_RE),
                    ("data_state", DATA_RE)):
        m = rx.search(text or "")
        if m:
            info[key] = m.group(1).strip()
    found = VERSION_RE.findall(text or "")
    if found:
        info.setdefault("version_tags", sorted(set(found)))
    return info


def audit_package(root, deep_super=True) -> dict:
    """审计一个卡刷包目录（解压后的），返回 {findings, versions, images, super}。"""
    root = Path(root)
    res = {"path": str(root), "findings": [], "versions": {}, "images": [],
           "super": None, "ok": False}

    def add(level, msg):
        res["findings"].append({"level": level, "msg": msg})

    if not root.is_dir():
        add("fail", "目录不存在：{}".format(root))
        return res

    images_dir = root / "images"
    if not images_dir.is_dir():
        add("fail", "缺少 images/ 目录")
        return res

    # ---- 镜像清单
    for p in sorted(images_dir.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        entry = {"name": name, "size": p.stat().st_size, "compressed": p.suffix == ".zst"}
        res["images"].append(entry)
    names = {e["name"] for e in res["images"]}
    has_super = "super.img" in names or "super.img.zst" in names
    if not has_super:
        add("fail", "images/ 里没有 super.img 或 super.img.zst")
    for req in REQUIRED_IMAGES:
        if req not in names:
            add("fail", "缺少必需镜像 images/{}".format(req))
    for opt in OPTIONAL_IMAGES:
        if opt not in names:
            add("warn", "没有 images/{}（可选，TWRP/基带另说）".format(opt))

    # ---- 刷机脚本 / 元数据
    scripts = [p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".bat", ".sh")]
    res["scripts"] = scripts
    if not scripts:
        add("warn", "根目录没有刷机脚本（.bat/.sh）")

    updater = root / "META-INF" / "com" / "google" / "android" / "update-binary"
    if not updater.is_file():
        add("fail", "缺少 META-INF/com/google/android/update-binary（TWRP 刷不了）")

    texts_by_enc = {}
    src_files = [p for p in sorted(root.glob("*.bat"))]
    if updater.is_file():
        src_files.append(updater)
    for p in src_files:
        for idx, text in enumerate(_text_variants(p)):
            texts_by_enc.setdefault(idx, []).append(text)
    versions = merge_versions(["\n".join(v) for _, v in sorted(texts_by_enc.items())])
    res["versions"] = versions
    if not versions.get("device_code"):
        add("warn", "刷机脚本里没读到机型代号（脚本可能不是现生成的）")
    if not versions.get("donor_version"):
        add("warn", "刷机脚本里没读到移植版本")

    # ---- ROOT 组件
    rm = root / "RootManager"
    res["root_managers"] = sorted(p.name for p in rm.glob("*.apk")) if rm.is_dir() else []
    if not res["root_managers"]:
        add("warn", "没有 RootManager/*.apk（选了 ROOT 也没管理器可装）")

    # ---- recovery 内解压工具
    for rel in ("bin/android/7zzs", "bin/android/zstd"):
        if not (root / rel).is_file():
            add("warn", "缺少 {}（recovery 里解压 super 用）".format(rel))

    # ---- super 布局
    if deep_super:
        sup = images_dir / "super.img"
        if sup.is_file():
            info = parse_super(sup)
            res["super"] = info
            if not info.get("ok"):
                add("fail", "super.img 解析失败：{}".format(info.get("error")))
        elif (images_dir / "super.img.zst").is_file():
            add("warn", "super.img 是 zst 压缩的，跳过布局解析（先 zstd -d 再 --super 单独跑）")

    res["ok"] = not any(f["level"] == "fail" for f in res["findings"])
    return res


# ================================================================ 比对
def compare_super(actual: dict, ref: dict, tolerance: int = 64 * MiB) -> list:
    """把实际 super 与基线 super 逐项比对。"""
    findings = []

    def add(level, msg):
        findings.append({"level": level, "msg": msg})

    if not actual.get("ok"):
        add("fail", "实际 super.img 无法解析：{}".format(actual.get("error")))
        return findings

    ref = ref or {}
    # ---- 容量
    ref_size = ref.get("file_size") or ref.get("super_capacity")
    if ref_size:
        if actual["file_size"] > ref_size:
            add("fail", "super.img {} 大于基线 {}（真机刷不进去）".format(
                human(actual["file_size"]), human(ref_size)))
        elif actual["file_size"] < ref_size - tolerance:
            add("warn", "super.img {} 比基线 {} 小 {}（-F 全量打包一般应相等）".format(
                human(actual["file_size"]), human(ref_size),
                human(ref_size - actual["file_size"])))
        else:
            add("ok", "super 容量 {} ≈ 基线 {}".format(
                human(actual["file_size"]), human(ref_size)))

    cap = actual.get("super_capacity")
    if cap and ref_size and cap != ref_size:
        add("fail", "block device super 大小 {} != 基线 {}".format(human(cap), human(ref_size)))

    # ---- 元数据头
    for key, label in (("metadata_version", "metadata 版本"),
                       ("metadata_slots", "metadata slots"),
                       ("logical_block_size", "逻辑块大小")):
        want = ref.get(key)
        got = actual.get(key)
        if want is None:
            continue
        if str(want) != str(got):
            add("fail", "{} {} != 基线 {}".format(label, got, want))
        else:
            add("ok", "{} = {}".format(label, got))

    want_flags = set(ref.get("flags") or []) - {"none"}
    got_flags = set(actual.get("flags") or []) - {"none"}
    if want_flags and want_flags != got_flags:
        add("fail", "header flags {} != 基线 {}".format(sorted(got_flags), sorted(want_flags)))
    elif want_flags:
        add("ok", "header flags = {}".format(sorted(got_flags)))

    # ---- group
    ref_groups = {g["name"]: g for g in (ref.get("groups") or [])}
    got_groups = {g["name"]: g for g in (actual.get("groups") or [])}
    for name, g in ref_groups.items():
        if name not in got_groups:
            add("fail", "缺少分区组 {}（基线 {:.0f}）".format(name, g.get("max_size") or 0))
            continue
        gm = got_groups[name].get("max_size") or 0
        rm = g.get("max_size") or 0
        if rm and gm and abs(gm - rm) > tolerance:
            add("fail", "分区组 {} 上限 {} != 基线 {}".format(name, human(gm), human(rm)))
        else:
            add("ok", "分区组 {} 上限 {}".format(name, human(gm)))
    for name in got_groups:
        if name not in ref_groups:
            add("warn", "多出分区组 {}（基线里没有）".format(name))

    # ---- 分区集合与尺寸
    ref_parts = {p["name"]: p for p in (ref.get("partitions") or [])}
    got_parts = {p["name"]: p for p in (actual.get("partitions") or [])}
    for name, p in ref_parts.items():
        if name not in got_parts:
            add("fail", "缺少分区 {}".format(name))
            continue
        g = got_parts[name]
        rs, gs = p.get("size") or 0, g.get("size") or 0
        if rs and gs > rs + tolerance:
            add("fail", "{} {:.2f} MiB 大于基线 {:.2f} MiB（+{:.2f} MiB）".format(
                name, gs / MiB, rs / MiB, (gs - rs) / MiB))
        elif rs and gs < rs - tolerance:
            add("warn", "{} {:.2f} MiB 小于基线 {:.2f} MiB（精简过头？）".format(
                name, gs / MiB, rs / MiB))
        else:
            add("ok", "{} {}".format(name, human(gs)))
        if p.get("group") and g.get("group") and p["group"] != g["group"]:
            add("fail", "{} 的分区组 {} != 基线 {}".format(name, g["group"], p["group"]))
    for name in got_parts:
        if name not in ref_parts:
            add("warn", "多出分区 {}（基线里没有，确认设备真的需要）".format(name))

    # ---- 汇总
    total = actual.get("partition_total") or 0
    ref_total = ref.get("partition_total") or 0
    if cap and total > cap:
        add("fail", "分区总和大盘 {} > super {}".format(human(total), human(cap)))
    else:
        add("ok", "分区合计 {}（{} 个分区）".format(human(total), len(got_parts)))
    if ref_total:
        msg = "分区合计 {}，基线 {}".format(human(total), human(ref_total))
        add("ok" if abs(total - ref_total) <= 512 * MiB else "warn", msg)

    # ---- slot 后缀策略：基线只有 _a
    ref_suffixed = any(name.endswith("_a") for name in ref_parts)
    got_suffixed = any(name.endswith("_a") for name in got_parts)
    if ref_suffixed != got_suffixed:
        add("fail", "分区命名风格不符：基线 {} 后缀，实际 {} 后缀".format(
            "有 _a" if ref_suffixed else "无", "有 _a" if got_suffixed else "无"))
    if any(name.endswith("_b") for name in got_parts):
        add("fail", "出现 _b 分区：14 Pro 参考布局里只有 _a（super 会多占一倍）")
    return findings


def compare_package(actual: dict, ref: dict, tolerance: int = 64 * MiB) -> list:
    findings = []

    def add(level, msg):
        findings.append({"level": level, "msg": msg})

    rv = (ref or {}).get("versions") or {}
    av = (actual or {}).get("versions") or {}
    for key, label in (("device_code", "目标机型代号"), ("device_name", "目标机型")):
        want, got = rv.get(key), av.get(key)
        if want and got and want.lower() != got.lower():
            add("fail", "{} {} != 基线 {}".format(label, got, want))
        elif want and got:
            add("ok", "{} = {}".format(label, got))
    donor = rv.get("donor_name")
    if donor and av.get("donor_name") and donor != av.get("donor_name"):
        add("warn", "移植来源 {} 与基线 {} 不同（路线变了就更新基线）".format(
            av["donor_name"], donor))
    if rv.get("base_version") and av.get("base_version"):
        if rv["base_version"] != av["base_version"]:
            add("warn", "底包版本 {} 与基线 {} 不同".format(
                av["base_version"], rv["base_version"]))
        else:
            add("ok", "底包版本 {}".format(av["base_version"]))

    rparts = {(p.get("name") or "") for p in (actual or {}).get("partitions") or []}
    if rparts:
        add("ok", "分区 {} 个".format(len(rparts)))

    ref_super = (ref or {}).get("super")
    got_super = (actual or {}).get("super")
    if ref_super and got_super:
        findings.extend(compare_super(got_super, ref_super, tolerance))
    return findings


# ================================================================ 输出
COLORS = {"ok": "\033[92m", "warn": "\033[93m", "fail": "\033[91m"}
RESET = "\033[0m"


def _color(level: str, text: str, enable: bool = True) -> str:
    if not enable:
        return text
    return "{}{}{}".format(COLORS.get(level, ""), text, RESET)


def print_findings(findings, title="", color=True) -> tuple:
    counts = {"ok": 0, "warn": 0, "fail": 0}
    print()
    if title:
        print("  {}".format(title))
    for f in findings:
        counts[f["level"]] = counts.get(f["level"], 0) + 1
        tag = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}[f["level"]]
        print("  {}".format(_color(f["level"], "[" + tag + "]", color)) + " " + f["msg"])
    print()
    print("  {} ok / {} warn / {} fail".format(counts["ok"], counts["warn"], counts["fail"]))
    return counts


def print_super_table(info: dict) -> None:
    if not info.get("ok"):
        print("  [FAIL] {}".format(info.get("error")))
        return
    print("  file        : {} ({})".format(info["path"], human(info["file_size"])))
    print("  metadata    : v{} / slots {} / max {} / lbs {}".format(
        info.get("metadata_version"), info.get("metadata_slots"),
        info.get("metadata_max_size"), info.get("logical_block_size")))
    print("  flags       : {}".format(", ".join(info.get("flags") or [])))
    for g in info.get("groups") or []:
        print("  group       : {:<32} max {}".format(g["name"], human(g.get("max_size"))))
    print()
    print("  {:<22} {:>14} {:>12} {:<28}".format("partition", "size", "first_sector", "group"))
    for p in info.get("partitions") or []:
        print("  {:<22} {:>14} {:>12} {:<28}".format(
            p["name"], human(p["size"]), p.get("first_sector", 0), p["group"]))
    print()
    print("  total {} / capacity {} / free {}".format(
        human(info.get("partition_total")), human(info.get("super_capacity")),
        human(info.get("free_bytes"))))


# ================================================================ 基线生成
def emit_reference(root, super_path=None) -> dict:
    """用已验证成品包生成基线 JSON。"""
    pkg = audit_package(root, deep_super=True)
    sup = pkg.get("super") or {}
    if not sup.get("ok") and super_path:
        sup = parse_super(super_path)
    ref = {
        "schema": 1,
        "generated_from": str(Path(root).resolve()),
        "versions": pkg.get("versions", {}),
        "flash_package": {
            "images": pkg.get("images", []),
            "root_managers": pkg.get("root_managers", []),
            "scripts": pkg.get("scripts", []),
            "required_images": REQUIRED_IMAGES,
        },
    }
    if sup.get("ok"):
        ref["super"] = {
            k: sup.get(k) for k in (
                "file_size", "metadata_version", "metadata_slots", "metadata_max_size",
                "logical_block_size", "flags", "groups", "partition_total",
                "super_capacity", "free_bytes")
        }
        ref["super"]["partitions"] = sup.get("partitions", [])
        ref["budget"] = sup.get("super_capacity") or sup.get("file_size")
    return ref


def load_reference(path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("  [WARN] 基线读取失败 {}: {}".format(path, exc), file=sys.stderr)
        return {}


# ================================================================ CLI
def _resolve_targets(args) -> tuple:
    """返回 (package_root_or_None, super_path_or_None)。"""
    missing = object()
    root = sup = missing
    if getattr(args, "package", None):
        root = Path(args.package)
    if getattr(args, "super", None):
        sup = Path(args.super)
    if getattr(args, "path", None):
        p = Path(args.path)
        if p.is_dir():
            root = p
        else:
            sup = p
    if root is missing and sup is missing:
        return None, None
    if root is missing:
        root = None
    if sup is missing:
        sup = None
    if root and sup is None:
        cand = root / "images" / "super.img"
        if cand.is_file():
            sup = cand
    return root, sup


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="参考包比对 / super.img 布局审计（不依赖 lpdumps.exe）")
    ap.add_argument("mode", choices=["super", "package", "all", "emit"],
                    help="super=只解析/比对 super；package=审计卡刷包目录；"
                         "all=目录 + 目录里的 super；emit=生成基线 JSON")
    ap.add_argument("path", nargs="?", help="super.img 或卡刷包目录")
    ap.add_argument("--package", help="卡刷包目录（覆盖 path）")
    ap.add_argument("--super", help="super.img 路径（覆盖 path）")
    ap.add_argument("--ref", default=str(DEFAULT_REF), help="基线 JSON（默认 reference/rom6_reference.json）")
    ap.add_argument("--emit", help="把基线写到这个路径（emit 模式默认 stdout）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--tolerance-mib", type=int, default=64, help="尺寸宽容值（MiB），默认 64")
    ap.add_argument("--strict", action="store_true", help="warn 也算失败")
    ap.add_argument("--no-color", action="store_true", help="关闭彩色输出")
    args = ap.parse_args(argv)
    color = not args.no_color and not args.json
    tol = max(0, args.tolerance_mib) * MiB
    root, sup = _resolve_targets(args)
    # package/all 模式下 super 由 audit_package 解析一次，避免重复比对
    if root and not args.super:
        sup = None

    # ---------- emit
    if args.mode == "emit":
        if not root:
            print("emit 需要卡刷包目录：python tools\\ref_check.py emit <目录> --emit out.json",
                  file=sys.stderr)
            return 2
        ref = emit_reference(root, sup)
        text = json.dumps(ref, ensure_ascii=False, indent=2)
        if args.emit:
            out = Path(args.emit)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
            print("  基线已写入 {}（{} 个分区）".format(
                out, len((ref.get("super") or {}).get("partitions") or [])))
        else:
            print(text)
        return 0

    if not root and not sup:
        print("需要 super.img 或卡刷包目录", file=sys.stderr)
        return 2

    reference = load_reference(args.ref) if args.ref else {}
    findings, result = [], {}

    # ---------- super
    if sup:
        info = parse_super(sup)
        result["super"] = info
        if not args.json:
            print_super_table(info)
        if reference.get("super"):
            findings.extend(compare_super(info, reference["super"], tol))
        elif not info.get("ok"):
            findings.append({"level": "fail", "msg": info.get("error", "解析失败")})

    # ---------- package
    if root:
        pkg = audit_package(root, deep_super=args.mode in ("package", "all"))
        result["package"] = pkg
        if not args.json and (pkg.get("super") or {}).get("ok"):
            print_super_table(pkg["super"])
        findings.extend(pkg["findings"])
        if reference and args.mode != "super":
            got_super = pkg.get("super")
            if got_super and got_super.get("ok") and reference.get("super"):
                findings.extend(compare_super(got_super, reference["super"], tol))
            findings.extend(compare_package({"versions": pkg.get("versions", {})},
                                            reference, tol))

    counts = {"ok": 0, "warn": 0, "fail": 0}
    for f in findings:
        counts[f["level"]] = counts.get(f["level"], 0) + 1

    if args.json:
        print(json.dumps({"findings": findings, "counts": counts,
                          "result": {k: {"ok": v.get("ok"),
                                         "path": v.get("path"),
                                         "file_size": v.get("file_size")}
                                     for k, v in result.items()}},
                         ensure_ascii=False, indent=2))
    else:
        print_findings(findings, title="与基线 {} 的比对结果".format(args.ref), color=color)

    if counts["fail"]:
        return 1
    if args.strict and counts["warn"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
