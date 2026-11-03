#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包阶段：super.img -> images/super.img.zst -> 卡刷包 zip

输出结构借鉴本机 X-MiPort 4.0.5 的 14 Pro 成品包（F:\\Rom\\X-MiPort-4.0.5）：

    bin/android/{7zzs,zstd}       Recovery 里解压/刷写用
    bin/Windows/{fastboot,...}    线刷脚本用
    images/super.img.zst          zstd 压缩的 super（TWRP 直接 pipe 刷入）
    images/*.img                  boot / vbmeta / 基带等固件
    images/recovery_twrp.img      TWRP（有就带上）
    META-INF/com/google/android/update-binary   现生成的 TWRP 刷机脚本
    X-MiPort-Flash.bat                           现生成的 Windows 线刷脚本

与参考包一致的关键点：
  * super 是 raw 7.75 GiB（lpmake -F），zstd 压缩后放 images/super.img.zst；
  * 卡刷包命名 ShennongPort_Mi14Pro_<版本>_<donor>_<md5>_<安卓>.zip，
    update-binary 会校验第 5 段 md5；
  * 固件镜像按 14 Pro 的分区名刷到 _a/_b 两个槽。

用法：
    python tools/package_zip.py [--no-compress] [--dry-run] [--json]
"""

import argparse
import hashlib
import json
import os
import re
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

DYNAMIC = {"system", "system_ext", "product", "odm", "vendor", "mi_ext",
           "vendor_dlkm", "system_dlkm", "super"}

# 14 Pro 固件分区 -> images 里的文件名（顺序照参考包 update-binary）
FLASH_MAP = [
    ("boot", "boot.img"),
    ("init_boot", "init_boot.img"),
    ("vendor_boot", "vendor_boot.img"),
    ("dtbo", "dtbo.img"),
    ("vbmeta", "vbmeta.img"),
    ("vbmeta_system", "vbmeta_system.img"),
    ("abl", "abl.img"),
    ("aop", "aop.img"),
    ("aop_config", "aop_config.img"),
    ("bluetooth", "bluetooth.img"),
    ("cpucp", "cpucp.img"),
    ("cpucp_dtb", "cpucp_dtb.img"),
    ("devcfg", "devcfg.img"),
    ("dsp", "dsp.img"),
    ("featenabler", "featenabler.img"),
    ("hyp", "hyp.img"),
    ("imagefv", "imagefv.img"),
    ("keymaster", "keymaster.img"),
    ("modem", "modem.img"),
    ("modemfirmware", "modemfirmware.img"),
    ("multiimgqti", "multiimgqti.img"),
    ("qupfw", "qupfw.img"),
    ("shrm", "shrm.img"),
    ("spuservice", "spuservice.img"),
    ("tz", "tz.img"),
    ("uefi", "uefi.img"),
    ("uefisecapp", "uefisecapp.img"),
    ("vm-bootsys", "vm-bootsys.img"),
    ("xbl", "xbl.img"),
    ("xbl_config", "xbl_config.img"),
    ("xbl_ramdump", "xbl_ramdump.img"),
    ("recovery", "recovery_twrp.img"),
]


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
    if ZSTD.is_file():
        cmd = [str(ZSTD), "-q", "-f", "-{}".format(level), "-T0", str(src), "-o", str(dst)]
        if subprocess.run(cmd).returncode == 0 and dst.is_file():
            return "tools/zstd.exe"
        return ""
    try:
        from compression import zstd as _zstd  # Python 3.14+
        Path(dst).write_bytes(_zstd.compress(Path(src).read_bytes(), level=level))
        return "python-compression.zstd"
    except Exception:
        return ""


def _touch_tree(root, epoch=1230768000):
    for cur, dirs, files in os.walk(str(root)):
        for name in files + dirs:
            try:
                os.utime(os.path.join(cur, name), (epoch, epoch))
            except OSError:
                pass
    try:
        os.utime(str(root), (epoch, epoch))
    except OSError:
        pass


def _versions(cfg, donor):
    v = sp.detect_versions(cfg)
    return {
        "port": v.get("port_os_version") or "UNKNOWN",
        "base": v.get("vendor_os_version") or "UNKNOWN",
        "donor": donor or "donor",
        "android": v.get("android_version") or "14",
    }


def _url_codename(url):
    """.../madrid-ota_full-OS4...zip -> madrid"""
    name = url.split("?", 1)[0].rstrip("/").split("/")[-1] if url else ""
    m = re.match(r"^([A-Za-z0-9_]+)-ota", name)
    return m.group(1).lower() if m else ""


def _stage_tools(stage):
    """展开 flashtools：bin/android、bin/Windows、META-INF 骨架。"""
    if FLASH_TOOLS.is_file():
        with zipfile.ZipFile(str(FLASH_TOOLS)) as z:
            z.extractall(str(stage))
        p = stage / "FlashWindows.bat"
        if p.is_file():
            p.unlink()
    # TWRP updater 用 7zzs 支持 zip64（flashtools 里只有 busybox/zstd）
    seven = sc.TOOLS / "xmiport" / "7zzs"
    if seven.is_file():
        dest = stage / "bin" / "android" / "7zzs"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(seven), str(dest))
    (stage / "images").mkdir(parents=True, exist_ok=True)


def _stage_firmware(stage):
    """复制 14 Pro 固件镜像到 images/（排除动态分区）。"""
    images = stage / "images"
    images.mkdir(parents=True, exist_ok=True)
    count = 0
    if sc.TGT_UNPACK.is_dir():
        for f in sc.TGT_UNPACK.glob("*.img"):
            if f.stem.lower() in DYNAMIC:
                continue
            shutil.copy2(str(f), str(images / f.name))
            count += 1
    twrp = sc.TGT_UNPACK / "firmware-update" / "recovery.img"
    if twrp.is_file():
        shutil.copy2(str(twrp), str(images / "recovery_twrp.img"))
    return count


def _present_images(stage):
    images = stage / "images"
    return [(part, name) for part, name in FLASH_MAP if (images / name).is_file()]


def _write_updater(stage, info):
    lines = [
        "#!/sbin/sh",
        "",
        'OUTFD=/proc/self/fd/$2',
        'ZIPFILE="$3"',
        "",
        "ui_print() {",
        '  echo -e "ui_print $1\\nui_print" >>$OUTFD;',
        "}",
        "",
        "package_extract_file() {",
        '  ui_print "- flashing $(basename $2)"',
        '  /tmp/bin/android/7zzs e -so "$ZIPFILE" "$1" > "$2"',
        "}",
        "",
        "package_extract_zstd() {",
        '  ui_print "- flashing super (zstd)"',
        '  /tmp/bin/android/7zzs e -so "$ZIPFILE" "$1" | /tmp/bin/android/zstd -d -c > "$2"',
        "}",
        "",
        "checkDevice() {",
        '  myDevice=$(getprop ro.product.name)',
        '  ui_print "  device: $myDevice"',
        '  if [ "$(echo $myDevice | grep shennong)" == "" ]; then',
        '    ui_print "- device mismatch, abort"',
        "    exit 1",
        "  fi",
        "}",
        "",
        'ui_print " "',
        'ui_print "  ShennongPort (port -> slim -> pack)"',
        'ui_print "  target : Xiaomi 14 Pro (shennong)"',
        'ui_print "  donor  : @@DONOR@@ / @@PORT@@"',
        'ui_print "  base   : @@BASE@@"',
        'ui_print "  android: @@ANDROID@@"',
        'ui_print " "',
        "",
        "[ -d /tmp ] && rm -rf /tmp",
        "mkdir -p /tmp",
        'unzip "$ZIPFILE" bin/android/zstd -d /tmp',
        'unzip "$ZIPFILE" bin/android/7zzs -d /tmp',
        "chmod -R 0755 /tmp",
        "",
        "checkDevice",
        "",
        'romName=$(basename $ZIPFILE)',
        'if echo "$romName" | grep -q "ShennongPort"; then',
        '  ui_print "- checking md5"',
        '  myHash=$(md5sum $ZIPFILE | head -c 10)',
        '  realHash=$(echo $romName | cut -d "_" -f 5)',
        '  if [ "$myHash" != "$realHash" ]; then',
        '    ui_print "- md5 mismatch: $myHash != $realHash"',
        "    exit 250",
        "  fi",
        "fi",
        "",
        'ui_print "- flashing firmware"',
        "dd if=/dev/zero of=/dev/block/bootdevice/by-name/frp",
    ]
    for part, name in _present_images(stage):
        for slot in ("a", "b"):
            lines.append(
                'package_extract_file "images/{0}" "/dev/block/bootdevice/by-name/{1}_{2}"'.format(
                    name, part, slot))
    lines += [
        "",
        "if [ -f images/super.img.zst ]; then",
        '  package_extract_zstd "images/super.img.zst" "/dev/block/bootdevice/by-name/super"',
        "fi",
        "",
        "for pname in odm mi_ext system vendor product system_ext odm_dlkm vendor_dlkm system_dlkm mi_product; do",
        "  [ -e /dev/block/mapper/${pname}_a ] && lptools unmap ${pname}_a && lptools map ${pname}_a",
        "done",
        "",
        "mount /data 2>/dev/null",
        "rm -rf /data/dalvik-cache/arm/* /data/dalvik-cache/arm64/* /data/system/package_cache/*",
        "bootctl set-active-boot-slot a",
        'ui_print "- done"',
        "exit 0",
        "",
    ]
    text = "\n".join(lines)
    for key, val in (("@@DONOR@@", info["donor"]), ("@@PORT@@", info["port"]),
                     ("@@BASE@@", info["base"]), ("@@ANDROID@@", info["android"])):
        text = text.replace(key, str(val))
    dest = stage / "META-INF" / "com" / "google" / "android" / "update-binary"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    return dest


def _write_flash_bat(stage, info):
    lines = [
        "@echo off",
        "cd %~dp0",
        "chcp 936 >nul",
        "title ShennongPort 14 Pro fastboot flash",
        "echo ============================================",
        "echo   ShennongPort  (port -^> slim -^> pack)",
        "echo   target : Xiaomi 14 Pro (shennong)",
        "echo   donor  : {donor} / {port}".format(**info),
        "echo   base   : {base}".format(**info),
        "echo ============================================",
        "echo.",
        "if not exist bin\\Windows\\fastboot.exe (",
        "  echo [!] bin\\Windows missing, please extract the zip completely",
        "  pause & exit /b 1",
        ")",
        "if exist images\\super.img.zst (",
        "  echo [*] decompressing super.img.zst ...",
        "  bin\\Windows\\zstd.exe --rm -d images\\super.img.zst -o images\\super.img",
        "  if errorlevel 1 ( echo [!] decompress failed & pause & exit /b 1 )",
        ")",
        "bin\\Windows\\fastboot getvar product 2>&1 | findstr /i shennong >nul",
        "if errorlevel 1 (",
        "  echo [!] product is not shennong, abort",
        "  pause & exit /b 1",
        ")",
        "echo [*] flashing firmware ...",
    ]
    for part, name in _present_images(stage):
        lines.append("bin\\Windows\\fastboot flash {0}_a images\\{1}".format(part, name))
        lines.append("bin\\Windows\\fastboot flash {0}_b images\\{1}".format(part, name))
    lines += [
        "echo [*] flashing super ...",
        "bin\\Windows\\fastboot flash super images\\super.img",
        "echo.",
        "echo [*] done. 'invalid sparse file format' is normal.",
        "pause",
        "",
    ]
    dest = stage / "X-MiPort-Flash.bat"
    dest.write_text("\r\n".join(lines), encoding="gbk", errors="replace")
    return dest


def build(cfg, compress=None, dry_run=False, quiet=False):
    super_img = sc.PACK_OUT / "super.img"
    if not super_img.is_file():
        return 1, {"error": "workspace/packed/super.img 不存在，请先跑移植/打包阶段"}

    if compress is None:
        raw = str(cfg.get("flat", {}).get("super_compress", "zstd")).strip().lower()
        compress = raw not in ("none", "false", "0", "off")

    donor = _url_codename(
        cfg.get("sections", {}).get("source", {}).get("url", "")) or "donor"
    info = _versions(cfg, donor)
    if dry_run:
        return 0, {"dry_run": True, "would_build": _rom_name(info, "0000000000"),
                   "super": str(super_img), "compress": compress}

    stage = sc.WORKSPACE / "package_stage"
    if stage.exists():
        shutil.rmtree(str(stage), ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)
    _stage_tools(stage)
    fw_count = _stage_firmware(stage)
    if not quiet:
        print("  [pack] images/: {} 个固件镜像".format(fw_count))

    keep_raw = str(cfg.get("flat", {}).get("keep_super_img", "false")).strip().lower() == "true"
    cleanup = str(cfg.get("flat", {}).get("cleanup_intermediate", "true")).strip().lower() == "true"
    super_bytes = super_img.stat().st_size
    free = _free_bytes(sc.WORKSPACE)
    if not quiet:
        print("  [pack] super.img {}, 剩余磁盘 {}".format(
            sc.human(super_bytes), sc.human(free) if free >= 0 else "?"))

    images = stage / "images"
    zst = images / "super.img.zst"
    zstd_name = ""
    if compress:
        need = int(super_bytes * 0.9) + (200 << 20)
        if 0 <= free < need:
            return 1, {"error": "磁盘不足：压缩 super 需要约 {}，只剩 {}。"
                                "可设 keep_super_img=false / 清理 workspace/download_*".format(
                                    sc.human(need), sc.human(free))}
        level = sc.cfg_int(cfg, "zstd_level", 12)
        if not quiet:
            print("  [pack] 压缩 images/super.img.zst (zstd level {}) ...".format(level))
        zstd_name = _zstd_compress(super_img, zst, level)
        if not zstd_name:
            return 1, {"error": "zstd 压缩失败（磁盘不足？）"}
        if not keep_raw:
            try:
                super_img.unlink()
                if not quiet:
                    print("  [pack] 已删除 raw super.img（keep_super_img=false）")
            except OSError:
                pass
    else:
        shutil.copy2(str(super_img), str(images / "super.img"))

    _write_updater(stage, info)
    _write_flash_bat(stage, info)

    _touch_tree(stage)
    if not SEVEN_ZIP.is_file():
        return 1, {"error": "tools/7z.exe 缺失"}
    payload_bytes = zst.stat().st_size if zst.is_file() else super_bytes
    free = _free_bytes(sc.WORKSPACE)
    need = payload_bytes + (300 << 20)
    if 0 <= free < need:
        return 1, {"error": "磁盘不足：7z 打包需要约 {}，只剩 {}。"
                            "可删 workspace/download_* 或已解压的 source_rom/target_rom".format(
                                sc.human(need), sc.human(free))}
    tmp_zip = sc.WORKSPACE / "rom_tmp.zip"
    if tmp_zip.exists():
        tmp_zip.unlink()
    cmd = [str(SEVEN_ZIP), "a", "-tzip", "-mx=1", str(tmp_zip), str(stage / "*")]
    if not quiet:
        print("  [pack] 7z 打包中（super.zst 约 6~7 GB，需要几分钟）...")
    if subprocess.run(cmd).returncode != 0 or not tmp_zip.is_file():
        return 1, {"error": "7z 打包失败（rc=2 通常是磁盘不足）"}

    md5 = _md5(tmp_zip)
    rom_name = _rom_name(info, md5)
    sc.OUT_DIR.mkdir(parents=True, exist_ok=True)
    final = sc.OUT_DIR / rom_name
    if final.exists():
        final.unlink()
    os.replace(tmp_zip, final)
    size = final.stat().st_size

    if cleanup:
        shutil.rmtree(str(stage), ignore_errors=True)

    summary = {
        "rom_name": rom_name,
        "path": str(final),
        "size": size,
        "md5": md5,
        "compressor": zstd_name or "none",
        "firmware_images": fw_count,
        "super_bytes": super_bytes,
        "layout": "xmiport/images",
        "ts": int(time.time()),
        "versions": info,
    }
    try:
        (sc.OUT_DIR / (rom_name + ".json")).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return 0, summary


def _rom_name(info, md5):
    return "ShennongPort_Mi14Pro_{ver}_{donor}_{md5}_{android}.zip".format(
        ver=info["port"], donor=info["donor"], md5=md5[:10], android=info["android"])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="打包卡刷包 zip（X-MiPort 布局）")
    ap.add_argument("--no-compress", action="store_true")
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
