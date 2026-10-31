#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源下载器：14PRO_SHALLOW_ROM 的 shennong_files/

14 Pro 的精简/修补离不开一批「14 Pro 专属」文件（相机、overlay、device_features、
displayconfig、fstab、TWRP 等），它们在上游仓库里合计约 310 MiB。合并版不把这
些二进制塞进本仓库，而是按清单下载、按大小校验、断点续传缓存到：

    assets/shennong_files/

下载源默认是上游仓库的 raw 地址，可用 config.ini 或环境变量换成镜像：

    [shennong] asset_base=https://ghfast.top/https://raw.githubusercontent.com/...
    SHENNONG_ASSET_BASE=...

用法：
    python tools/assets.py list
    python tools/assets.py fetch            # 补齐缺失
    python tools/assets.py fetch fstab.qcom MSA.apk
    python tools/assets.py verify
"""

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stage_common as sc  # noqa: E402

UPSTREAM_BASE = ("https://raw.githubusercontent.com/XHR222/"
                 "14PRO_SHALLOW_ROM/main/shennong_files/")

# name -> (size, 用途)
ASSETS = {
    "fstab.qcom": (11535, "vendor_boot / vendor 的 fstab（14 Pro 分区表）"),
    "device_features.zip": (7830, "product/etc/device_features（机型特性）"),
    "displayconfig.zip": (6284, "product/etc/displayconfig（屏幕参数）"),
    "overlay.zip": (50970556, "product/overlay（RRO 主题/资源叠加）"),
    "PowerKeeper.zip": (5045757, "system/app/PowerKeeper（精准电量）"),
    "MiAONService.apk": (127390, "product/app/MiAONService（注视感知）"),
    "MSA.apk": (8538, "product/app/MSA（广告服务占位）"),
    "bootanimation.zip": (188118, "product/media/bootanimation.zip（开机动画）"),
    "CameraTools_beta.zip": (4928546, "product/app/CameraTools（相机标定）"),
    "MiuiCamera.apk.1": (83886080, "MiuiCamera 分卷 1/3"),
    "MiuiCamera.apk.2": (83886080, "MiuiCamera 分卷 2/3"),
    "MiuiCamera.apk.3": (14421444, "MiuiCamera 分卷 3/3"),
    "recovery.zip": (70207334, "firmware-update/TWRP recovery"),
}

# 精简段真正会用到的资源（缺了对应步骤就跳过）
NEEDED_BY_STAGE = {
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
    "recovery": ["recovery.zip"],
}


def asset_dir(cfg=None):
    cfg = cfg or sc.read_ini()
    custom = cfg.get("sections", {}).get("shennong", {}).get("asset_dir", "").strip()
    d = Path(custom) if custom else sc.SHENNONG_ASSETS
    if not d.is_absolute():
        d = sc.ROOT / d
    return d


def base_url(cfg=None):
    cfg = cfg or sc.read_ini()
    custom = cfg.get("sections", {}).get("shennong", {}).get("asset_base", "").strip()
    if not custom:
        custom = os.environ.get("SHENNONG_ASSET_BASE", "").strip()
    return (custom or UPSTREAM_BASE).rstrip("/") + "/"


def local_path(name, cfg=None):
    return asset_dir(cfg) / name


def have(name, cfg=None):
    p = local_path(name, cfg)
    try:
        return p.is_file() and p.stat().st_size == ASSETS[name][0]
    except OSError:
        return False


def missing(names, cfg=None):
    return [n for n in names if not have(n, cfg)]


def _download_one(name, cfg=None, quiet=False):
    size, _use = ASSETS[name]
    dest = local_path(name, cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    url = base_url(cfg) + urllib.request.quote(name)
    offset = part.stat().st_size if part.exists() else 0
    if offset > size:
        try:
            part.unlink()
        except OSError:
            pass
        offset = 0
    req = urllib.request.Request(url, headers={"User-Agent": "shennong-port-assets"})
    if offset:
        req.add_header("Range", "bytes={}-".format(offset))
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            if offset and resp.status != 206:
                offset = 0
            mode = "ab" if offset else "wb"
            got = offset
            last = 0.0
            with open(part, mode) as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    now = time.time()
                    if not quiet and now - last > 0.5:
                        last = now
                        pct = got * 100.0 / max(size, 1)
                        sys.stdout.write("\r    {:>6.1f}%  {:>10} / {:<10}  {}".format(
                            pct, sc.human(got), sc.human(size), name))
                        sys.stdout.flush()
    except urllib.error.HTTPError as e:
        if not quiet:
            print("\n    [X] {} HTTP {}: {}".format(name, e.code, url))
        return False
    except Exception as e:
        if not quiet:
            print("\n    [X] {} 下载失败: {}".format(name, e))
        return False

    if part.stat().st_size != size:
        if not quiet:
            print("\n    [X] {} 大小不符: {} != {}".format(
                name, part.stat().st_size, size))
        return False
    os.replace(part, dest)
    if not quiet:
        sys.stdout.write("\r    [OK] {:>10}  {}\n".format(sc.human(size), name))
        sys.stdout.flush()
    return True


def fetch(names=None, cfg=None, quiet=False):
    """下载缺失资源；返回 (ok_count, missing_list)。已存在的不重复下。"""
    cfg = cfg or sc.read_ini()
    names = list(names) if names else list(ASSETS)
    need = [n for n in names if not have(n, cfg)]
    if not need:
        if not quiet:
            print("  所有资源已就绪: {}".format(asset_dir(cfg)))
        return 0, []
    if not quiet:
        total = sum(ASSETS[n][0] for n in need)
        print("  需要下载 {} 个文件，共 {}".format(len(need), sc.human(total)))
        print("  来源: {}".format(base_url(cfg)))
        print("  缓存: {}".format(asset_dir(cfg)))
    ok = 0
    for name in need:
        if _download_one(name, cfg, quiet=quiet):
            ok += 1
    left = missing(names, cfg)
    if not quiet:
        print("  完成: {}/{}，仍缺 {} 个".format(ok, len(need), len(left)))
    return ok, left


def ensure_for_steps(steps, cfg=None, offline=False, quiet=False):
    """精简段调用：按要启用的步骤补齐资源，返回缺失清单（不抛异常）。"""
    names = []
    for step in steps:
        for n in NEEDED_BY_STAGE.get(step, []):
            if n not in names:
                names.append(n)
    cfg = cfg or sc.read_ini()
    if offline:
        return missing(names, cfg)
    fetch(names, cfg, quiet=quiet)
    return missing(names, cfg)


def cmd_list():
    cfg = sc.read_ini()
    d = asset_dir(cfg)
    print()
    print("  资源目录: {}".format(d))
    print("  下载源:   {}".format(base_url(cfg)))
    print()
    total = 0
    for name, (size, use) in ASSETS.items():
        p = d / name
        state = "OK " if p.is_file() and p.stat().st_size == size else "缺失"
        if p.is_file():
            total += p.stat().st_size
        print("    [{}] {:>10}  {:<24} {}".format(state, sc.human(size), name, use))
    print()
    print("  已缓存合计: {}".format(sc.human(total)))
    return 0


def cmd_verify():
    cfg = sc.read_ini()
    bad = []
    for name, (size, _use) in ASSETS.items():
        p = local_path(name, cfg)
        if not p.is_file():
            bad.append((name, "缺失"))
        elif p.stat().st_size != size:
            bad.append((name, "大小 {} != {}".format(p.stat().st_size, size)))
    if bad:
        for name, why in bad:
            print("  [X] {:<24} {}".format(name, why))
        return 1
    print("  全部 {} 个资源校验通过".format(len(ASSETS)))
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="shennong_files 资源下载器")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="列出资源与缓存状态")
    p_fetch = sub.add_parser("fetch", help="下载缺失资源")
    p_fetch.add_argument("names", nargs="*", help="只下指定文件（默认全部）")
    sub.add_parser("verify", help="校验大小")
    args = ap.parse_args()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "fetch":
        names = args.names or None
        if names:
            unknown = [n for n in names if n not in ASSETS]
            if unknown:
                print("  未知资源: {}".format(",".join(unknown)))
                return 2
        _ok, left = fetch(names)
        return 0 if not left else 1
    if args.cmd == "verify":
        return cmd_verify()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
