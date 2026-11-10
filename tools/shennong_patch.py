#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精简阶段（二）：14 Pro 功能修补 / shennong patch

把 14PRO_SHALLOW_ROM 的 make.sh 逐段翻译成 Python。make.sh 依赖 bash、sudo、
Linux 版 magiskboot/ksud/zstd，本文件只保留「对分区文件系统」的操作，因此
Windows / Linux 都能跑，且能被 XMAPort 的移植结果直接复用。

覆盖的 make.sh 段落（步骤 id 对应）：
    overlay          product/overlay            ← overlay.zip
    device_features  product/etc/device_features← device_features.zip
    displayconfig    product/etc/displayconfig  ← displayconfig.zip
    powerkeeper      system/app/PowerKeeper     ← PowerKeeper.zip
    miaon            product/app/MiAONService   ← MiAONService.apk
    camera           product/priv-app/MiuiCamera← MiuiCamera.apk.1/2/3 + CameraTools
    msa              product/app/MSA            ← MSA.apk
    bootanimation    product/media/bootanimation.zip
    build_props      统一 build.prop（版本/日期/机型名/构建者）
    density          默认密度 560
    aptx             vendor aptX Lossless 属性
    recovery_stub    删除 vendor/recovery-from-boot.p、install-recovery.sh
    init_qcom        删除 init.qcom.rc 里的 qti-testscripts
    fstab            替换 vendor/etc/fstab.qcom
    firmware         内置 TWRP（recovery.zip → firmware-update）
    signature        移除 Android 签名校验（可选，apktool）
    icons            完美图标（可选，需联网）
    kernelsu         init_boot 注入 KernelSU（可选，仅 Linux）

未覆盖、需要 Linux 工具链的：vendor_boot 里 first_stage_ramdisk/fstab.qcom 的
替换（magiskboot + cpio）。见 docs/LIMITS.md，本文件会明确 skip 而不是假装成功。

用法：
    python tools/shennong_patch.py list
    python tools/shennong_patch.py apply [--steps overlay,camera,...]
                                          [--dry-run] [--offline] [--json]
"""

import argparse
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
import assets as asset_mod  # noqa: E402

ASSET_STEPS = {
    "overlay": ["overlay.zip"],
    "device_features": ["device_features.zip"],
    "displayconfig": ["displayconfig.zip"],
    "powerkeeper": ["PowerKeeper.zip"],
    "miaon": ["MiAONService.apk"],
    "camera": ["MiuiCamera.apk.1", "MiuiCamera.apk.2", "MiuiCamera.apk.3",
               "CameraTools_beta.zip"],
    "msa": ["MSA.apk"],
    "bootanimation": ["bootanimation.zip"],
    "fstab": ["fstab.qcom"],
    "firmware": ["recovery.zip"],
}

ALL_STEPS = [
    "overlay", "device_features", "displayconfig", "powerkeeper", "miaon",
    "camera", "msa", "bootanimation", "build_props", "density", "aptx",
    "recovery_stub", "init_qcom", "fstab", "firmware",
    # 可选（默认关闭）
    "signature", "icons", "kernelsu",
]

STASH = sc.WORKSPACE / ".shennong_stash"


# --------------------------------------------------------------------------- 上下文
class Ctx:
    def __init__(self, cfg, dry_run=False, offline=False, quiet=False):
        self.cfg = cfg
        self.dry_run = dry_run
        self.offline = offline
        self.quiet = quiet
        self.asset_dir = asset_mod.asset_dir(cfg)
        sh = cfg.get("sections", {}).get("shennong", {})
        self.opts = sh
        self.device = (sh.get("device") or "shennong").strip()
        self.results = []
        self.notes = []
        self.versions = detect_versions(cfg)
        self.build_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.build_utc = str(int(time.time()))
        self.parts = {}

    # ---- 路径
    def src(self, part):
        return sc.content_root(part)

    def tgt(self, part):
        return sc.target_content_root(part)

    def opt(self, key, default=""):
        return (self.opts.get(key) or default).strip()

    def opt_bool(self, key, default=False):
        raw = self.opt(key)
        if not raw:
            return default
        return raw.lower() in ("1", "true", "yes", "on", "y")

    def asset(self, name):
        return self.asset_dir / name

    # ---- 输出
    def log(self, msg):
        if not self.quiet:
            print("  [patch] " + msg, flush=True)
        self.notes.append(msg)

    def rec(self, step, status, detail=""):
        self.results.append({"step": step, "status": status, "detail": detail})
        if status == "skip" and detail and not self.quiet:
            print("  [patch] 跳过 {}: {}".format(step, detail))
        if status == "fail":
            print("  [patch] [X] {}: {}".format(step, detail))

    # ---- 受保护写操作（dry-run 下只记录）
    def act(self, desc):
        if self.dry_run:
            self.log("[预演] " + desc)
            return False
        return True


# --------------------------------------------------------------------------- 版本
def _url_of(cfg, section):
    return (cfg.get("sections", {}).get(section, {}).get("url") or "").strip()


def _version_from_url(url):
    """从官方 OTA 直链里取版本号：.../OS4.0.27.0.XEOCNM/madrid-ota_full-....zip"""
    try:
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        segs = [s for s in path.split("/") if s]
        for seg in segs:
            if re.match(r"^OS[\d.]+\.[A-Z0-9]+$", seg, re.I) or re.match(r"^V\d{3}\.[\d.]+", seg):
                return seg
        # 退而求其次：从 zip 文件名里找
        m = re.search(r"-(OS[\d.]+\.[A-Z0-9]+)-", url, re.I)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _zip_name(url):
    return url.split("?", 1)[0].rstrip("/").split("/")[-1] if url else ""


def _android_version(url):
    name = _zip_name(url)
    m = re.search(r"-user-(\d+)\.", name) or re.search(r"_(\d+(?:\.\d+)?)\.zip$", name)
    if m:
        return m.group(1).split(".")[0]
    return ""


def _alias(version):
    """make.sh: s/OS1/V816/g。OS2/3/4 保持原样（14 Pro 底包多为 OS1/OS2/OS3）。"""
    if version.upper().startswith("OS1"):
        return "V816" + version[3:]
    return version


def detect_versions(cfg):
    src_url = _url_of(cfg, "source")
    tgt_url = _url_of(cfg, "target")
    v = {
        "port_os_version": _version_from_url(src_url),
        "vendor_os_version": _version_from_url(tgt_url),
        "port_zip": _zip_name(src_url),
        "vendor_zip": _zip_name(tgt_url),
        "android_version": _android_version(src_url) or "14",
    }
    v["port_version"] = _alias(v["port_os_version"])
    v["vendor_version"] = _alias(v["vendor_os_version"])
    return v


def _prop_get(path, key):
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def detect_baselines(ctx):
    """移植包 / 底包的基线版本号（make.sh 里 ro.system.build.id / ro.vendor.build.id）。"""
    v = ctx.versions
    v["port_base_line"] = _prop_get(ctx.src("system") / "build.prop", "ro.system.build.id")
    vendor_bp = ctx.tgt("vendor") / "build.prop"
    v["vendor_base_line"] = _prop_get(vendor_bp, "ro.vendor.build.id")
    v["port_security_patch"] = _prop_get(ctx.src("system") / "build.prop",
                                          "ro.build.version.security_patch")
    v["vendor_security_patch"] = _prop_get(vendor_bp, "ro.vendor.build.security_patch")
    return v


# --------------------------------------------------------------------------- 文件工具
def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    except OSError:
        return None


def _write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _replace_prop_line(text, key, value):
    """替换 key=...（存在则改，不存在则追加），返回 (new_text, changed)。"""
    pat = re.compile(r"^" + re.escape(key) + r"=.*$", re.M)
    if pat.search(text):
        new = pat.sub(key + "=" + value, text, count=1)
        return new, new != text
    if not text.endswith("\n"):
        text += "\n"
    return text + key + "=" + value + "\n", True


def _sub_prop_line(text, key, value):
    """只替换已存在的 key=...（对齐 make.sh 的 sed 语义，不凭空追加）。"""
    pat = re.compile(r"^" + re.escape(key) + r"=.*$", re.M)
    if not pat.search(text):
        return text, False
    new = pat.sub(key + "=" + value, text, count=1)
    return new, new != text


def _clear_dir(path):
    p = Path(path)
    if not p.is_dir():
        p.mkdir(parents=True, exist_ok=True)
        return
    for child in p.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(str(child), ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            pass


def _unzip_to(zip_path, dest, clear=True):
    if clear:
        _clear_dir(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path)) as z:
        z.extractall(str(dest))


def _zip_size(zip_path):
    total = 0
    with zipfile.ZipFile(str(zip_path)) as z:
        for info in z.infolist():
            total += info.file_size
    return total


def _find_case_insensitive(root, name):
    """在 root 顶层找名字不区分大小写的子项。"""
    p = Path(root) / name
    if p.exists():
        return p
    if not Path(root).is_dir():
        return None
    low = name.lower()
    for child in Path(root).iterdir():
        if child.name.lower() == low:
            return child
    return None


# --------------------------------------------------------------------------- 步骤
def step_overlay(ctx):
    zip_path = ctx.asset("overlay.zip")
    dest = ctx.src("product") / "overlay"
    if not dest.parent.is_dir():
        return "skip", "缺少 product 分区"
    if not ctx.act("清空 product/overlay 并解压 overlay.zip"):
        return "ok", "[预演]"
    _unzip_to(zip_path, dest, clear=True)
    return "ok", "overlay 已替换"


def step_device_features(ctx):
    dest = ctx.src("product") / "etc" / "device_features"
    if not dest.parent.is_dir():
        return "skip", "缺少 product/etc"
    if not ctx.act("替换 product/etc/device_features"):
        return "ok", "[预演]"
    _unzip_to(ctx.asset("device_features.zip"), dest, clear=True)
    return "ok", "device_features 已替换"


def step_displayconfig(ctx):
    dest = ctx.src("product") / "etc" / "displayconfig"
    if not dest.parent.is_dir():
        return "skip", "缺少 product/etc"
    if not ctx.act("替换 product/etc/displayconfig"):
        return "ok", "[预演]"
    _unzip_to(ctx.asset("displayconfig.zip"), dest, clear=True)
    return "ok", "displayconfig 已替换"


def step_powerkeeper(ctx):
    dest = ctx.src("system") / "app" / "PowerKeeper"
    if not dest.parent.is_dir():
        return "skip", "缺少 system/app"
    if not ctx.act("替换 system/app/PowerKeeper"):
        return "ok", "[预演]"
    _unzip_to(ctx.asset("PowerKeeper.zip"), dest, clear=True)
    return "ok", "PowerKeeper 已替换"


def step_miaon(ctx):
    app_dir = ctx.src("product") / "app"
    if not app_dir.is_dir():
        return "skip", "缺少 product/app"
    if not ctx.act("替换 product/app/MiAONService"):
        return "ok", "[预演]"
    for child in app_dir.iterdir():
        if child.name.lower().startswith("miaonservice"):
            sc.remove_path(child)
    dest = app_dir / "MiAONService"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(ctx.asset("MiAONService.apk")), str(dest / "MiAONService.apk"))
    return "ok", "MiAONService 已替换"


def _concat_apk(ctx, out_path):
    parts = [ctx.asset("MiuiCamera.apk.{}".format(i)) for i in (1, 2, 3)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    with open(tmp, "wb") as w:
        for p in parts:
            with open(p, "rb") as r:
                shutil.copyfileobj(r, w, 1 << 20)
    os.replace(tmp, out_path)
    return sum(p.stat().st_size for p in parts)


def step_camera(ctx):
    product = ctx.src("product")
    priv = product / "priv-app" / "MiuiCamera"
    if not (product / "priv-app").is_dir():
        return "skip", "缺少 product/priv-app"
    if not ctx.act("拼接 MiuiCamera.apk 1/2/3 并替换"):
        return "ok", "[预演]"
    _clear_dir(priv)
    size = _concat_apk(ctx, priv / "MiuiCamera.apk")
    tools_zip = ctx.asset("CameraTools_beta.zip")
    if tools_zip.is_file():
        _unzip_to(tools_zip, product / "app", clear=False)
    return "ok", "相机已替换 ({})".format(sc.human(size))


def step_msa(ctx):
    msa = ctx.src("product") / "app" / "MSA"
    if not msa.parent.is_dir():
        return "skip", "缺少 product/app"
    if not ctx.act("替换 product/app/MSA 为占位包"):
        return "ok", "[预演]"
    _clear_dir(msa)
    shutil.copy2(str(ctx.asset("MSA.apk")), str(msa / "MSA.apk"))
    return "ok", "MSA 已替换"


def step_bootanimation(ctx):
    dest = ctx.src("product") / "media" / "bootanimation.zip"
    if not dest.parent.is_dir():
        return "skip", "缺少 product/media"
    if not ctx.act("替换 product/media/bootanimation.zip"):
        return "ok", "[预演]"
    shutil.copy2(str(ctx.asset("bootanimation.zip")), str(dest))
    return "ok", "开机动画已替换"


def step_build_props(ctx):
    v = ctx.versions
    if not ctx.act("统一 build.prop（版本/日期/机型名/构建者）"):
        return "ok", "[预演]"
    changed = 0

    def _apply(path):
        nonlocal changed
        text = _read(path)
        if text is None:
            return
        old = text
        if v.get("port_os_version") and v.get("vendor_os_version"):
            text = text.replace(v["port_os_version"], v["vendor_os_version"])
        if v.get("port_version") and v.get("vendor_version"):
            text = text.replace(v["port_version"], v["vendor_version"])
        if v.get("port_base_line") and v.get("vendor_base_line"):
            text = text.replace(v["port_base_line"], v["vendor_base_line"])
        text, _ = _sub_prop_line(text, "build.date", ctx.build_time)
        text, _ = _sub_prop_line(text, "build.date.utc", ctx.build_utc)
        text, _ = _sub_prop_line(text, "ro.build.user", "YuKongA")
        text, _ = _sub_prop_line(text, "ro.product.product.name", ctx.device)
        if text != old:
            _write(path, text)
            changed += 1

    for bp in ctx.src("system").rglob("build.prop"):
        _apply(bp)
    for bp in ctx.src("product").rglob("build.prop"):
        _apply(bp)
    for bp in ctx.src("system_ext").rglob("build.prop"):
        _apply(bp)
    # 底包侧：只改日期与增量版本号
    vendor_root = ctx.tgt("vendor")
    if vendor_root.is_dir():
        for bp in vendor_root.rglob("*build.prop"):
            text = _read(bp)
            if text is None:
                continue
            old = text
            text, _ = _sub_prop_line(text, "build.date", ctx.build_time)
            text, _ = _sub_prop_line(text, "build.date.utc", ctx.build_utc)
            if v.get("port_os_version"):
                text, _ = _sub_prop_line(text, "ro.mi.os.version.incremental",
                                         v["port_os_version"])
            if text != old:
                _write(bp, text)
                changed += 1
    return "ok", "{} 个 build.prop 已更新".format(changed)


def step_density(ctx):
    bp = ctx.src("product") / "etc" / "build.prop"
    if not bp.is_file():
        return "skip", "缺少 product/etc/build.prop"
    density = ctx.opt("density", "560")
    if not ctx.act("设置 persist.miui.density_v2={}".format(density)):
        return "ok", "[预演]"
    text = _read(bp) or ""
    new, changed = _sub_prop_line(text, "persist.miui.density_v2", density)
    if changed:
        _write(bp, new)
    return ("ok", "密度={}".format(density)) if changed else ("skip", "未找到密度键")


def step_aptx(ctx):
    bp = ctx.tgt("vendor") / "build.prop"
    if not bp.is_file():
        return "skip", "缺少 vendor/build.prop（vendor 需解包）"
    prop = "persist.vendor.qcom.bluetooth.aptxadaptiver2_2_support=true"
    if not ctx.act("追加 aptX Lossless 属性"):
        return "ok", "[预演]"
    text = _read(bp) or ""
    if prop.split("=")[0] in text:
        return "skip", "属性已存在"
    if not text.endswith("\n"):
        text += "\n"
    _write(bp, text + prop + "\n")
    return "ok", "aptX Lossless 已添加"


def step_recovery_stub(ctx):
    vendor = ctx.tgt("vendor")
    if not vendor.is_dir():
        return "skip", "缺少 vendor（vendor 需解包）"
    if not ctx.act("删除 vendor/recovery-from-boot.p 与 install-recovery.sh"):
        return "ok", "[预演]"
    removed = 0
    for rel in ("recovery-from-boot.p", "bin/install-recovery.sh"):
        p = vendor / rel
        if p.exists() and sc.remove_path(p):
            removed += 1
    return "ok", "移除 {} 个恢复脚本".format(removed)


def step_init_qcom(ctx):
    rc_file = ctx.tgt("vendor") / "etc" / "init" / "hw" / "init.qcom.rc"
    if not rc_file.is_file():
        return "skip", "缺少 init.qcom.rc"
    if not ctx.act("删除 init.qcom.rc 里的 qti-testscripts"):
        return "ok", "[预演]"
    lines = _read(rc_file).splitlines(True)
    kept = [ln for ln in lines if "start qti-testscripts" not in ln]
    if len(kept) == len(lines):
        return "skip", "未找到 qti-testscripts"
    _write(rc_file, "".join(kept))
    return "ok", "已删除 {} 行".format(len(lines) - len(kept))


def step_fstab(ctx):
    dest = ctx.tgt("vendor") / "etc" / "fstab.qcom"
    if not dest.parent.is_dir():
        return "skip", "缺少 vendor/etc"
    if not ctx.act("替换 vendor/etc/fstab.qcom"):
        return "ok", "[预演]"
    shutil.copy2(str(ctx.asset("fstab.qcom")), str(dest))
    return "ok", "vendor fstab 已替换"


def step_firmware(ctx):
    """recovery.zip（TWRP）解到 target_payload/firmware-update，打包段会带进 zip。"""
    dest = sc.TGT_UNPACK / "firmware-update"
    if not ctx.act("内置 TWRP 到 firmware-update"):
        return "ok", "[预演]"
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(ctx.asset("recovery.zip"))) as z:
        z.extractall(str(dest))
    return "ok", "TWRP 已放入 firmware-update"


def step_signature(ctx):
    """移除 Android 签名校验（make.sh 的 services.jar smali 补丁）。"""
    jar = ctx.src("system") / "framework" / "services.jar"
    if not jar.is_file():
        return "skip", "缺少 system/framework/services.jar"
    java = _find_java()
    apktool = sc.TOOLS / "apktool.jar"
    if not java or not apktool.is_file():
        return "skip", "没有 java / apktool.jar"
    if not ctx.act("apktool 反编译 services.jar 并去掉签名校验"):
        return "ok", "[预演]"
    work = sc.WORKSPACE / "apk_services"
    if work.exists():
        shutil.rmtree(str(work), ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    apk = work / "services.apk"
    shutil.copy2(str(jar), str(apk))
    dec = work / "services"
    cmd = [java, "-jar", str(apktool), "d", "-q", "-f", str(apk), "-o", str(dec)]
    if subprocess.run(cmd).returncode != 0:
        return "fail", "apktool 反编译失败"
    patched = _patch_signature_smali(dec)
    if patched == 0:
        return "skip", "没有找到签名校验 smali（可能已打过补丁）"
    out = work / "services_new.jar"
    cmd = [java, "-jar", str(apktool), "b", "-q", "-f", "-c", str(dec), "-o", str(out)]
    if subprocess.run(cmd).returncode != 0 or not out.is_file():
        return "fail", "apktool 重编译失败"
    shutil.copy2(str(out), str(jar))
    return "ok", "已修改 {} 个 smali".format(patched)


def _patch_signature_smali(dec_root):
    marker = "getMinimumSignatureSchemeVersionForTargetSdk"
    bases = [
        dec_root / "smali_classes2" / "com" / "android" / "server" / "pm",
        dec_root / "smali_classes2" / "com" / "android" / "server" / "pm" / "pkg" / "parsing",
    ]
    count = 0
    for base in bases:
        if not base.is_dir():
            continue
        for f in base.glob("*.smali"):
            text = _read(f)
            if not text or marker not in text:
                continue
            lines = text.splitlines(True)
            idx = next((i for i, ln in enumerate(lines) if marker in ln), None)
            if idx is None:
                continue
            move = next(((i, ln) for i, ln in enumerate(lines[idx:], idx)
                         if "move-result" in ln), None)
            if not move:
                continue
            i1, ln1 = move
            digits = re.sub(r"[^0-9]", "", ln1.split("move-result", 1)[1])
            if not digits:
                continue
            lines[idx:i1 + 1] = ["    const/4 v{}, 0x0\n".format(digits)]
            _write(f, "".join(lines))
            count += 1
    return count


def _find_java():
    bundled = sc.TOOLS / "jre" / "bin" / "java.exe"
    if bundled.is_file():
        return str(bundled)
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        cand = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if cand.is_file():
            return str(cand)
    found = shutil.which("java")
    return found or ""


def step_icons(ctx):
    """完美图标：把 Perfect-Icons 项目的图标包并入 product/media/theme。"""
    theme = ctx.src("product") / "media" / "theme"
    if not theme.is_dir():
        return "skip", "缺少 product/media/theme"
    if ctx.offline:
        return "skip", "offline 模式不联网"
    if not ctx.act("下载 Perfect-Icons 并重建 icons / dynamicicons"):
        return "ok", "[预演]"
    cache = sc.ASSETS / "Perfect-Icons.zip"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.is_file():
        # 镜像链：codeload → Gitee 镜像 → 公益加速前缀，任一可用即可
        if not asset_mod.fetch_icons(cache, ctx.cfg, quiet=ctx.quiet):
            return "fail", "下载失败（全部镜像不可用，可用 config.ini icons_url= 指定源）"
    icons_root = sc.WORKSPACE / "icons_src"
    if icons_root.exists():
        shutil.rmtree(str(icons_root), ignore_errors=True)
    with zipfile.ZipFile(str(cache)) as z:
        z.extractall(str(icons_root))
    # 解压后顶层是 Perfect-Icons-...-main/
    tops = [p for p in icons_root.iterdir() if p.is_dir()]
    if not tops:
        return "fail", "图标包解压结果为空"
    src_icons = tops[0] / "icons"
    if not src_icons.is_dir():
        return "fail", "图标包里没有 icons/ 目录"
    # 删除和 dynamic 图标冲突的包
    dynamic = theme / "miui_mod_icons" / "dynamic"
    if dynamic.is_dir():
        for pkg in dynamic.iterdir():
            target = src_icons / pkg.name
            if target.is_dir():
                shutil.rmtree(str(target), ignore_errors=True)
    shutil.rmtree(str(src_icons / "com.xiaomi.scanner"), ignore_errors=True)
    # icons.zip：res/drawable-xxhdpi
    res = icons_root / "res" / "drawable-xxhdpi"
    res.parent.mkdir(parents=True, exist_ok=True)
    if res.exists():
        shutil.rmtree(str(res), ignore_errors=True)
    shutil.move(str(src_icons), str(res))
    _zip_tree(icons_root / "res", theme / "default" / "icons")
    # dynamicicons.zip
    dyn_out = theme / "default" / "dynamicicons"
    layers = []
    for rel in (("themes", "Hyper"), ("themes", "common")):
        p = tops[0] / rel[0] / rel[1] / "layer_animating_icons"
        if p.is_dir():
            layers.append(p)
    if layers:
        _zip_multi(layers, dyn_out)
    shutil.rmtree(str(icons_root), ignore_errors=True)
    return "ok", "完美图标已重建"


def _zip_tree(src_dir, out_file):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_name(out_file.name + ".tmp")
    with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as z:
        for cur, _dirs, files in os.walk(str(src_dir)):
            for f in files:
                full = Path(cur) / f
                z.write(str(full), str(full.relative_to(src_dir.parent)))
    os.replace(tmp, out_file)


def _zip_multi(src_dirs, out_file):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_name(out_file.name + ".tmp")
    with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as z:
        for src in src_dirs:
            for cur, _dirs, files in os.walk(str(src)):
                for f in files:
                    full = Path(cur) / f
                    z.write(str(full), str(full.relative_to(src.parent)))
    os.replace(tmp, out_file)


def step_kernelsu(ctx):
    return "skip", "KernelSU 注入需要 Linux ksud/magiskboot，Windows 版不提供"


STEPS = {
    "overlay": step_overlay,
    "device_features": step_device_features,
    "displayconfig": step_displayconfig,
    "powerkeeper": step_powerkeeper,
    "miaon": step_miaon,
    "camera": step_camera,
    "msa": step_msa,
    "bootanimation": step_bootanimation,
    "build_props": step_build_props,
    "density": step_density,
    "aptx": step_aptx,
    "recovery_stub": step_recovery_stub,
    "init_qcom": step_init_qcom,
    "fstab": step_fstab,
    "firmware": step_firmware,
    "signature": step_signature,
    "icons": step_icons,
    "kernelsu": step_kernelsu,
}


# --------------------------------------------------------------------------- 运行
def select_steps(ctx, requested=None):
    """决定这次要跑哪些步骤：requested > config [shennong] steps/skip_steps > 默认。"""
    if requested:
        return [s for s in requested if s in STEPS]
    raw = ctx.opt("steps")
    if raw:
        wanted = [s.strip() for s in raw.replace(";", ",").split(",") if s.strip()]
        base = [s for s in ALL_STEPS if s in wanted or "all" in wanted]
    else:
        base = ["overlay", "device_features", "displayconfig", "powerkeeper",
                "miaon", "camera", "msa", "bootanimation", "build_props",
                "density", "aptx", "recovery_stub", "init_qcom", "fstab",
                "firmware"]
        if ctx.opt_bool("enable_signature", False):
            base.append("signature")
        if ctx.opt_bool("enable_icons", False):
            base.append("icons")
        if ctx.opt_bool("enable_kernelsu", False):
            base.append("kernelsu")
    skip = [s.strip() for s in ctx.opt("skip_steps").replace(";", ",").split(",") if s.strip()]
    return [s for s in ALL_STEPS if s in base and s not in skip]


def run(cfg, steps=None, dry_run=False, offline=False, quiet=False):
    ctx = Ctx(cfg, dry_run=dry_run, offline=offline, quiet=quiet)
    if not sc.content_root("system").is_dir():
        return 2, {"error": "workspace/source_filesystem 里没有 system 分区，请先跑移植阶段"}

    detect_baselines(ctx)
    todo = select_steps(ctx, steps)
    if not quiet:
        v = ctx.versions
        print("  [patch] 移植包版本: {}  底包版本: {}".format(
            v.get("port_os_version") or "?", v.get("vendor_os_version") or "?"))
        print("  [patch] 设备代号: {}  步骤: {}".format(ctx.device, ",".join(todo)))

    # 资源
    needed = []
    for s in todo:
        needed.extend(ASSET_STEPS.get(s, []))
    missing = []
    if not offline:
        _ok, missing = asset_mod.fetch(list(dict.fromkeys(needed)), cfg, quiet=quiet)
    else:
        missing = asset_mod.missing(list(dict.fromkeys(needed)), cfg)

    for step in todo:
        req = ASSET_STEPS.get(step, [])
        lack = [n for n in req if n in missing]
        if lack:
            ctx.rec(step, "skip", "缺少资源: {}".format(", ".join(lack)))
            continue
        fn = STEPS[step]
        try:
            status, detail = fn(ctx)
        except Exception as e:
            status, detail = "fail", "{}: {}".format(type(e).__name__, e)
        ctx.rec(step, status, detail)
        if not quiet and status == "ok":
            print("  [patch] [OK] {}  {}".format(step, detail))

    ok = sum(1 for r in ctx.results if r["status"] == "ok")
    skip = sum(1 for r in ctx.results if r["status"] == "skip")
    fail = sum(1 for r in ctx.results if r["status"] == "fail")
    summary = {
        "versions": ctx.versions,
        "device": ctx.device,
        "dry_run": bool(dry_run),
        "results": ctx.results,
        "ok": ok, "skip": skip, "fail": fail,
        "ts": int(time.time()),
    }
    try:
        sc.WORKSPACE.mkdir(parents=True, exist_ok=True)
        (sc.WORKSPACE / "shennong_patch.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    if not quiet:
        print("  [patch] 完成: OK={} 跳过={} 失败={}".format(ok, skip, fail))
    return (0 if fail == 0 else 1), summary


# --------------------------------------------------------------------------- CLI
def cmd_list():
    print()
    print("  14 Pro 修补步骤（来自 14PRO_SHALLOW_ROM/make.sh）:")
    for s in ALL_STEPS:
        tag = "（可选）" if s in ("signature", "icons", "kernelsu") else ""
        print("    {:<16} {}{}".format(s, STEPS[s].__doc__ or "", tag))
    print()
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="14 Pro 功能修补 / shennong patch")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="列出步骤")
    p = sub.add_parser("apply", help="执行修补")
    p.add_argument("--steps", default="", help="逗号分隔，默认按配置")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--offline", action="store_true", help="不下载资源，缺了就跳过")
    p.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "apply":
        cfg = sc.read_ini()
        steps = [s.strip() for s in args.steps.split(",") if s.strip()]
        rc, summary = run(cfg, steps or None, dry_run=args.dry_run,
                          offline=args.offline, quiet=False)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        return rc
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
