#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包阶段：super.img -> images/super.img.zst -> 卡刷包 zip

输出结构对齐参考 14 Pro 成品包：

    bin/android/{7zzs,zstd}       Recovery 里解压/刷写用
    bin/Windows/{fastboot,...}    线刷脚本用
    images/super.img.zst          zstd 压缩的 super（TWRP 直接 pipe 刷入）
    images/*.img                  boot / init_boot / vbmeta / 基带 / ROOT 补丁
    images/recovery_twrp.img      TWRP（有就带上）
    META-INF/com/google/android/update-binary   现生成的 TWRP 刷机脚本
    Flash-Windows.bat                           现生成的 Windows 线刷脚本

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

# 14 Pro 固件分区 -> images 里的文件名（boot / init_boot / recovery 单独处理）
FLASH_MAP = [
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
]

# ROOT 方式 -> images 里的 init_boot 文件
ROOT_OPTIONS = [
    (1, "NoROOT", "init_boot_official.img"),
    (2, "Magisk", "init_boot_magisk.img"),
    (3, "KernelSU", "init_boot_ksu.img"),
    (4, "SukiSU-Ultra", "init_boot_sukisu.img"),
    (5, "KernelSU-Next", "init_boot_ksu-next.img"),
    (6, "Kitsune Mask", "init_boot_kitsune-mask.img"),
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


def _decompress_zst(src, dst):
    """用 tools/zstd.exe 解压；失败返回 False。"""
    if not ZSTD.is_file():
        return False
    cmd = [str(ZSTD), "-q", "-f", "-d", str(src), "-o", str(dst)]
    return subprocess.run(cmd).returncode == 0 and Path(dst).is_file()


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


def _stage_firmware(stage, cfg=None):
    """复制固件 / ROOT 补丁 / recovery 到 images/。

    BOOT 相关：
      * boot.img                    ← 底包 boot（官方）
      * init_boot_official.img      ← 底包 init_boot（若 assets 没有就用它）
      * init_boot_magisk/ksu/...    ← assets/root_images 里的 ROOT 补丁
    recovery 优先级：
      1. config [packing] recovery_img=<本地 path>
      2. target_payload/firmware-update/recovery.img（精简段从 recovery.zip 解出）
      3. flash_recovery=false 时不要
    """
    images = stage / "images"
    images.mkdir(parents=True, exist_ok=True)
    count = 0
    if sc.TGT_UNPACK.is_dir():
        for f in sc.TGT_UNPACK.glob("*.img"):
            if f.stem.lower() in DYNAMIC:
                continue
            # 优先用打包阶段修补过的镜像（vbmeta* 已禁验），否则用原始固件
            patched = sc.PACK_OUT / f.name
            src = patched if patched.is_file() else f
            shutil.copy2(str(src), str(images / f.name))
            count += 1

    flat = (cfg or {}).get("flat", {}) if isinstance(cfg, dict) else {}

    # ROOT 补丁镜像（assets/root_images）
    root_dir = str(flat.get("root_images", "assets/root_images")).strip() or "assets/root_images"
    rd = Path(root_dir)
    if not rd.is_absolute():
        rd = sc.ROOT / rd
    if rd.is_dir():
        for f in sorted(rd.glob("init_boot_*.img")):
            shutil.copy2(str(f), str(images / f.name))
        for extra in ("boot_apatch.img", "boot_folkpatch.img"):
            if (rd / extra).is_file():
                shutil.copy2(str(rd / extra), str(images / extra))
    # 没有 official 就用底包 init_boot.img
    if not (images / "init_boot_official.img").is_file() and (images / "init_boot.img").is_file():
        shutil.copy2(str(images / "init_boot.img"), str(images / "init_boot_official.img"))

    flash_recovery = str(flat.get("flash_recovery", "true")).strip().lower() not in (
        "false", "0", "off", "no")
    if not flash_recovery:
        return count
    custom = str(flat.get("recovery_img", "")).strip()
    if custom:
        p = Path(custom)
        if not p.is_absolute():
            p = sc.ROOT / p
        # 允许放 .img.zst（GitHub 单文件 100MB 限制）
        cand = p if p.is_file() else Path(str(p) + ".zst")
        if cand.is_file():
            if cand.suffix.lower() == ".zst":
                if _decompress_zst(cand, images / "recovery_twrp.img"):
                    print("  [pack] recovery: 解压自定义 {}".format(cand))
                    return count
                print("  [pack] [!] 解压失败: {}".format(cand))
            else:
                shutil.copy2(str(cand), str(images / "recovery_twrp.img"))
                print("  [pack] recovery: 使用自定义 {}".format(cand))
                return count
        print("  [pack] [!] recovery_img 不存在: {}".format(p))
    twrp = sc.TGT_UNPACK / "firmware-update" / "recovery.img"
    if twrp.is_file():
        shutil.copy2(str(twrp), str(images / "recovery_twrp.img"))
    return count


def _present_images(stage):
    images = stage / "images"
    return [(part, name) for part, name in FLASH_MAP if (images / name).is_file()]


def _write_updater(stage, info):
    images = stage / "images"
    fw = [(part, name) for part, name in FLASH_MAP if (images / name).is_file()]
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
        'have_img() { unzip -l "$ZIPFILE" | grep -q "images/$1"; }',
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
        "select_root() {",
        "  ROOT_SEL=1",
        '  ui_print " "',
        '  ui_print "====== ROOT ======"',
        '  ui_print " <1> NoROOT          <2> Magisk"',
        '  ui_print " <3> KernelSU        <4> SukiSU-Ultra"',
        '  ui_print " <5> KernelSU-Next   <6> Kitsune Mask"',
        '  ui_print " Volume- : next      Volume+ : confirm"',
        "  while true; do",
        '    ev=$(getevent -qlc 1 2>/dev/null)',
        '    case "$ev" in',
        "      *KEY_VOLUMEDOWN*DOWN*)",
        "        ROOT_SEL=$((ROOT_SEL + 1))",
        '        [ $ROOT_SEL -gt 6 ] && ROOT_SEL=1',
        '        ui_print "- current: $ROOT_SEL"',
        "        ;;",
        "      *KEY_VOLUMEUP*DOWN*) break ;;",
        "    esac",
        "  done",
        "}",
        "",
        "ask_twrp() {",
        "  TWRP_YES=0",
        '  if have_img "recovery_twrp.img"; then',
        '    ui_print " "',
        '    ui_print "- Flash TWRP? Volume+ yes / Volume- no"',
        "    while true; do",
        '      ev=$(getevent -qlc 1 2>/dev/null)',
        '      case "$ev" in',
        "        *KEY_VOLUMEUP*DOWN*) TWRP_YES=1; break ;;",
        "        *KEY_VOLUMEDOWN*DOWN*) break ;;",
        "      esac",
        "    done",
        "  fi",
        "}",
        "",
        'ui_print " "',
        'ui_print "  ShennongPort"',
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
        '    ui_print "- md5 mismatch"',
        "    exit 250",
        "  fi",
        "fi",
        "",
        'ui_print "- flashing boot"',
    ]
    if (images / "boot.img").is_file():
        lines += [
            'package_extract_file "images/boot.img" "/dev/block/bootdevice/by-name/boot_a"',
            'package_extract_file "images/boot.img" "/dev/block/bootdevice/by-name/boot_b"',
        ]
    lines += [
        "",
        "select_root",
        'ROOT_IMG="init_boot_official.img"',
        "case $ROOT_SEL in",
        '  2) ROOT_IMG="init_boot_magisk.img" ;;',
        '  3) ROOT_IMG="init_boot_ksu.img" ;;',
        '  4) ROOT_IMG="init_boot_sukisu.img" ;;',
        '  5) ROOT_IMG="init_boot_ksu-next.img" ;;',
        '  6) ROOT_IMG="init_boot_kitsune-mask.img" ;;',
        "esac",
        'if ! have_img "$ROOT_IMG"; then ROOT_IMG="init_boot_official.img"; fi',
        'package_extract_file "images/$ROOT_IMG" "/dev/block/bootdevice/by-name/init_boot_a"',
        'package_extract_file "images/$ROOT_IMG" "/dev/block/bootdevice/by-name/init_boot_b"',
        "",
        "ask_twrp",
        '[ $TWRP_YES -eq 1 ] && package_extract_file "images/recovery_twrp.img" "/dev/block/bootdevice/by-name/recovery_a"',
        '[ $TWRP_YES -eq 1 ] && package_extract_file "images/recovery_twrp.img" "/dev/block/bootdevice/by-name/recovery_b"',
        "",
        'ui_print "- flashing firmware"',
        "dd if=/dev/zero of=/dev/block/bootdevice/by-name/frp",
    ]
    for part, name in fw:
        for slot in ("a", "b"):
            lines.append(
                'package_extract_file "images/{0}" "/dev/block/bootdevice/by-name/{1}_{2}"'.format(
                    name, part, slot))
    lines += [
        "",
        'if have_img "super.img.zst"; then',
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
    images = stage / "images"
    fw = [(part, name) for part, name in FLASH_MAP if (images / name).is_file()]
    lines = [
        "@echo off",
        "cd %~dp0",
        "chcp 936 >nul",
        "title ShennongPort - Xiaomi 14 Pro",
        "echo ============================================",
        "echo   ShennongPort",
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
        "echo.",
        "set wipeData=n",
        "set /p wipeData=Format data? (y/n): ",
        'if /i "%wipeData%"=="y" bin\\Windows\\fastboot -w',
        "echo.",
        "echo ======== ROOT ========",
        "echo  1 NoROOT",
        "echo  2 Magisk",
        "echo  3 KernelSU",
        "echo  4 SukiSU-Ultra",
        "echo  5 KernelSU-Next",
        "echo  6 Kitsune Mask",
        "echo =======================",
        "set rootType=1",
        "set /p rootType=Select [1-6]: ",
        'if "%rootType%"=="" set rootType=1',
        "set INIT_BOOT=init_boot_official.img",
        'if "%rootType%"=="2" set INIT_BOOT=init_boot_magisk.img',
        'if "%rootType%"=="3" set INIT_BOOT=init_boot_ksu.img',
        'if "%rootType%"=="4" set INIT_BOOT=init_boot_sukisu.img',
        'if "%rootType%"=="5" set INIT_BOOT=init_boot_ksu-next.img',
        'if "%rootType%"=="6" set INIT_BOOT=init_boot_kitsune-mask.img',
        "if not exist images\\%INIT_BOOT% set INIT_BOOT=init_boot_official.img",
        "echo [*] root image: %INIT_BOOT%",
        "echo [*] flashing boot / init_boot ...",
        "bin\\Windows\\fastboot flash boot_a images\\boot.img",
        "bin\\Windows\\fastboot flash boot_b images\\boot.img",
        "bin\\Windows\\fastboot flash init_boot_a images\\%INIT_BOOT%",
        "bin\\Windows\\fastboot flash init_boot_b images\\%INIT_BOOT%",
        "echo.",
    ]
    if (images / "recovery_twrp.img").is_file():
        lines += [
            "set twrpOrNot=n",
            "set /p twrpOrNot=Flash TWRP? (y/n): ",
            'if /i not "%twrpOrNot%"=="y" goto AFTER_TWRP',
            "bin\\Windows\\fastboot flash recovery_a images\\recovery_twrp.img",
            "bin\\Windows\\fastboot flash recovery_b images\\recovery_twrp.img",
            ":AFTER_TWRP",
            "echo.",
        ]
    lines += ["echo [*] flashing firmware ..."]
    for part, name in fw:
        if part in ("vbmeta", "vbmeta_system"):
            # 与参考脚本一致：刷 vbmeta 时同时关闭 verity + verification
            prefix = "bin\\Windows\\fastboot --disable-verity --disable-verification flash"
        else:
            prefix = "bin\\Windows\\fastboot flash"
        lines.append("{0} {1}_a images\\{2}".format(prefix, part, name))
        lines.append("{0} {1}_b images\\{2}".format(prefix, part, name))
    lines += [
        "echo [*] flashing super ...",
        "bin\\Windows\\fastboot flash super images\\super.img",
        "echo.",
        "echo [*] set active slot a ...",
        "bin\\Windows\\fastboot set_active a",
        "echo.",
        "echo [*] done. 'invalid sparse file format' is normal.",
        "echo [*] rebooting ...",
        "bin\\Windows\\fastboot reboot",
        "pause",
        "",
    ]
    dest = stage / "Flash-Windows.bat"
    dest.write_text("\n".join(lines), encoding="gbk", errors="replace")
    return dest


def _check_vbmeta(images):
    """确认打包的 vbmeta 已经关了 verity+verification（TWRP 卡刷靠它）。"""
    pat = bytes.fromhex("0000000300000000617662746F6F6C20")
    bad = []
    for p in images.glob("vbmeta*.img"):
        try:
            d = p.read_bytes()
        except OSError:
            continue
        if not d.startswith(b"AVB0") or pat not in d:
            bad.append(p.name)
    if bad:
        print("  [pack] [!] vbmeta 未打 0x3 补丁: {}".format(",".join(bad)))
        print("  [pack] [!] 线刷会用 --disable-verity --disable-verification，"
              "但 TWRP 卡刷可能因 dm-verity 卡一屏")
    else:
        print("  [pack] vbmeta: verity + verification 已关闭")


def _write_readme(stage, info):
    """zip 根目录的中文说明（GBK，方便 Windows 记事本直接打开）。"""
    has_twrp = (stage / "images" / "recovery_twrp.img").is_file()
    lines = [
        "ShennongPort 14 Pro 一体包",
        "==========================================",
        "目标机型 : Xiaomi 14 Pro (shennong)",
        "移植来源 : {donor} / {port}".format(**info),
        "底包版本 : {base}".format(**info),
        "安卓版本 : {android}".format(**info),
        "",
        "【方式一：Windows 线刷】",
        "1. 把本 zip 完整解压到一个目录（不要只解压一半）",
        "2. 手机进入 fastboot，连电脑，装好驱动",
        "3. 双击 Flash-Windows.bat，按提示选择是否格式化 data、ROOT 方式、是否刷 TWRP",
        "4. 首次刷机建议格式化 data（会清空数据）",
        "",
        "【ROOT 方式（线刷/卡刷都可选）】",
        "1 NoROOT   2 Magisk   3 KernelSU",
        "4 SukiSU-Ultra   5 KernelSU-Next   6 Kitsune Mask",
        "",
        "【方式二：Recovery 卡刷】",
        "1. 不要解压 zip，把整个 zip 放进手机存储",
        "2. 进 TWRP -> 安装 -> 选择本 zip -> 滑动刷入",
        "3. 按音量[-]切换 ROOT 方式，音量[+]确认；再按音量键选择是否刷 TWRP",
        "   本包{}包含 TWRP 镜像。".format("" if has_twrp else "不"),
        "",
        "【校验】",
        "文件名第 5 段是 zip 的 md5 前 10 位；",
        "卡刷脚本会自动校验，改名会导致校验失败。",
        "",
        "【注意】",
        "- 需要解锁 Bootloader；刷机有风险，后果自负。",
        "- 如果下载到的是 .7z.001 分卷，先用 7-Zip 解压 .001，",
        "  得到本 zip 后再按上面步骤操作。",
        "- super 是 raw 镜像，压缩在 images/super.img.zst 里，",
        "  刷机脚本会先解压，请预留至少 10 GB 磁盘空间。",
        "",
    ]
    dest = stage / "刷机说明.txt"
    dest.write_text("\n".join(lines), encoding="gbk", errors="replace")
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
    fw_count = _stage_firmware(stage, cfg)
    _check_vbmeta(stage / "images")
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
    _write_readme(stage, info)

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
    ap = argparse.ArgumentParser(description="打包卡刷包 zip（一体包布局）")
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
