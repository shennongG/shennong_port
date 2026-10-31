#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包阶段：super.img → super.zst → 卡刷包 zip

对应 14PRO_SHALLOW_ROM/make.sh 末尾「生成 super.img / 输出卡刷包」两段：

    zstd -12 super.img -o super.zst --rm
    7z a miui_<device>_<port_os_version>.zip images/*
    rom_name = SHENNONG_ShalloW_<port_os_version>_<md5前10位>_<android>.0.zip

差异（合并版有意为之）：
  * super.img 由 XMAPort 的 lpmake 生成，本文件只负责压缩 + 组装 zip；
  * 固件镜像从 target_payload 里挑（boot / dtbo / vbmeta* / vendor_boot …），
    TWRP（精简段 recovery 步骤放入 firmware-update）会覆盖同名文件；
  * 压缩器优先用 tools/zstd.exe，其次用 Python 3.14 自带 compression.zstd，
    都没有就把 super.img 原样放进 zip（并明确告警）。

用法：
    python tools/package_zip.py [--no-compress] [--dry-run] [--json]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stage_common as sc  # noqa: E402
import shennong_patch as sp  # noqa: E402

SEVEN_ZIP = sc.TOOLS / "7z.exe"
ZSTD = sc.TOOLS / "zstd.exe"
FLASH_TOOLS = sc.TOOLS / "flashtools.zip"

FIRMWARE_GLOBS = (
    "boot.img", "init_boot.img", "vendor_boot.img", "dtbo.img", "recovery.img",
    "vbmeta*.img", "super_empty.img", "modem.img", "dsp.img", "bluetooth.img",
    "xbl*.img", "abl.img", "tz*.img", "hyp*.img", "keymaster*.img",
    "spunvm.img", "uefisecapp*.img", "qupfw*.img", "devcfg*.img", "cmnlib*.img",
    "featenabler*.img", "aop*.img", "multiimgoem*.img", "qseecom*.img",
)


def _md5(path, chunk=8 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _free_bytes(path):
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return -1


def _zstd_compress(src, dst, level=12):
    """返回压缩器名称；失败返回空串。"""
    if ZSTD.is_file():
        cmd = [str(ZSTD), "-q", "-f", "-{}".format(level), "-T0", str(src), "-o", str(dst)]
        if subprocess.run(cmd).returncode == 0 and dst.is_file():
            return "tools/zstd.exe"
        return ""
    try:
        from compression import zstd as _zstd  # Python 3.14+
        data = Path(src).read_bytes()
        Path(dst).write_bytes(_zstd.compress(data, level=level))
        return "python-compression.zstd"
    except Exception:
        return ""


def _touch_tree(root, epoch=1230768000):
    """把 staging 里所有文件的 mtime 固定（2009-01-01），让 zip 可复现。"""
    for cur, dirs, files in os.walk(str(root)):
        for name in files + dirs:
            p = os.path.join(cur, name)
            try:
                os.utime(p, (epoch, epoch))
            except OSError:
                pass
    try:
        os.utime(str(root), (epoch, epoch))
    except OSError:
        pass


def _stage_firmware(stage):
    """把 target_payload 里的固件镜像复制进 firmware-update。"""
    fw = stage / "firmware-update"
    fw.mkdir(parents=True, exist_ok=True)
    count = 0
    if sc.TGT_UNPACK.is_dir():
        for pat in FIRMWARE_GLOBS:
            for f in sc.TGT_UNPACK.glob(pat):
                if f.is_file() and f.name.lower() != "super.img":
                    shutil.copy2(str(f), str(fw / f.name))
                    count += 1
    # TWRP（精简段放的）覆盖同名
    extra = sc.TGT_UNPACK / "firmware-update"
    if extra.is_dir():
        for f in extra.rglob("*"):
            if f.is_file():
                dest = fw / f.relative_to(extra)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dest))
                count += 1
    return count


def build(cfg, compress=None, dry_run=False, quiet=False):
    super_img = sc.PACK_OUT / "super.img"
    if not super_img.is_file():
        return 1, {"error": "workspace/packed/super.img 不存在，请先跑移植/打包阶段"}

    if compress is None:
        raw = str(cfg.get("flat", {}).get("super_compress", "zstd")).strip().lower()
        compress = raw not in ("none", "false", "0", "off")

    name_hint = _rom_name(cfg, md5="0000000000")
    if dry_run:
        return 0, {"dry_run": True, "would_build": name_hint,
                   "super": str(super_img), "compress": compress}

    stage = sc.WORKSPACE / "package_stage"
    if stage.exists():
        try:
            shutil.rmtree(str(stage), ignore_errors=True)
        except OSError:
            pass
    stage.mkdir(parents=True, exist_ok=True)

    # 1) 固件
    fw_count = _stage_firmware(stage)
    if not quiet:
        print("  [pack] firmware-update: {} 个镜像".format(fw_count))

    keep_raw = str(cfg.get("flat", {}).get("keep_super_img", "false")).strip().lower() == "true"
    cleanup = str(cfg.get("flat", {}).get("cleanup_intermediate", "true")).strip().lower() == "true"
    super_bytes = super_img.stat().st_size
    free = _free_bytes(sc.WORKSPACE)
    if not quiet:
        print("  [pack] super.img {}, 剩余磁盘 {}".format(
            sc.human(super_bytes), sc.human(free) if free >= 0 else "?"))

    # 2) super 压缩（先确认磁盘装得下 zst，再动手）
    zstd_name = ""
    if compress:
        need = int(super_bytes * 0.55) + (200 << 20)
        if 0 <= free < need:
            return 1, {"error": "磁盘不足：压缩 super 需要约 {}，只剩 {}。"
                                "可设 keep_super_img=false / 清理 workspace/download_*".format(
                                    sc.human(need), sc.human(free))}
        level = sc.cfg_int(cfg, "zstd_level", 12)
        if not quiet:
            print("  [pack] 压缩 super.img (zstd level {}) ...".format(level))
        zstd_name = _zstd_compress(super_img, stage / "super.zst", level)
        if zstd_name:
            if not quiet:
                print("  [pack] super.zst 完成 ({})".format(zstd_name))
            # raw super 占 7.75 GiB；zip 里已经有 zst，默认不再保留 raw
            if not keep_raw:
                try:
                    super_img.unlink()
                    if not quiet:
                        print("  [pack] 已删除 raw super.img（keep_super_img=false）")
                except OSError:
                    pass
        else:
            if not quiet:
                print("  [pack] [!] 没有可用的 zstd，改为直接打包 super.img")
    if not (stage / "super.zst").is_file():
        # 不复制 7.75GB：同盘硬链接，失败才退回复制
        link = stage / "super.img"
        try:
            os.link(str(super_img), str(link))
        except OSError:
            try:
                shutil.copy2(str(super_img), str(link))
            except OSError as e:
                return 1, {"error": "无法把 super.img 放进 staging: {}".format(e)}

    # 3) 刷机脚本
    if FLASH_TOOLS.is_file():
        with zipfile.ZipFile(str(FLASH_TOOLS)) as z:
            z.extractall(str(stage))
        if not quiet:
            print("  [pack] 刷机脚本已展开")
    elif not quiet:
        print("  [pack] [!] tools/flashtools.zip 缺失，zip 里不会有刷机脚本")

    # 4) 固定时间戳（可复现）后 7z 打包
    _touch_tree(stage)
    if not SEVEN_ZIP.is_file():
        return 1, {"error": "tools/7z.exe 缺失"}
    zst = stage / "super.zst"
    payload_bytes = zst.stat().st_size if zst.is_file() else super_bytes
    free = _free_bytes(sc.WORKSPACE)
    need = payload_bytes + (200 << 20)
    if 0 <= free < need:
        return 1, {"error": "磁盘不足：7z 打包需要约 {}，只剩 {}。"
                            "可删 workspace/download_* 或已解压的 source_rom/target_rom".format(
                                sc.human(need), sc.human(free))}
    tmp_zip = sc.WORKSPACE / "rom_tmp.zip"
    if tmp_zip.exists():
        tmp_zip.unlink()
    cmd = [str(SEVEN_ZIP), "a", "-tzip", "-mx=1", str(tmp_zip), str(stage / "*")]
    if not quiet:
        print("  [pack] 7z 打包中（super 镜像很大，需要几分钟）...")
    rc = subprocess.run(cmd).returncode
    if rc != 0 or not tmp_zip.is_file():
        return 1, {"error": "7z 打包失败 (rc={})".format(rc)}

    md5 = _md5(tmp_zip)
    rom_name = _rom_name(cfg, md5=md5)
    sc.OUT_DIR.mkdir(parents=True, exist_ok=True)
    final = sc.OUT_DIR / rom_name
    if final.exists():
        final.unlink()
    os.replace(tmp_zip, final)
    size = final.stat().st_size

    # 5) 清理 staging（zst / 刷机脚本 / super 硬链接），CI 上能省 4~5 GB
    if cleanup:
        try:
            shutil.rmtree(str(stage), ignore_errors=True)
        except OSError:
            pass

    summary = {
        "rom_name": rom_name,
        "path": str(final),
        "size": size,
        "md5": md5,
        "compressor": zstd_name or "none",
        "firmware_images": fw_count,
        "super_bytes": super_bytes,
        "ts": int(time.time()),
        "versions": sp.detect_versions(cfg),
    }
    try:
        (sc.OUT_DIR / (rom_name + ".json")).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return 0, summary


def _rom_name(cfg, md5):
    v = sp.detect_versions(cfg)
    ver = v.get("port_os_version") or v.get("vendor_os_version") or "UNKNOWN"
    android = v.get("android_version") or "14"
    return "SHENNONG_ShalloW_{}_{}_{}.0.zip".format(ver, md5[:10], android)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="打包卡刷包 zip")
    ap.add_argument("--no-compress", action="store_true", help="不压缩 super.img")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = sc.read_ini()
    rc, summary = build(cfg, compress=(False if args.no_compress else None),
                        dry_run=args.dry_run)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if rc == 0 and summary.get("path"):
        print("  [pack] 输出: {}  ({})".format(summary["path"], sc.human(summary["size"])))
    elif rc != 0:
        print("  [pack] [X] {}".format(summary.get("error", "失败")))
    return rc


if __name__ == "__main__":
    sys.exit(main())
