#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源下载器：14 Pro 专属资源的远程拉取与缓存

14 Pro 的精简/修补离不开一批「14 Pro 专属」文件（相机、overlay、device_features、
displayconfig、fstab、TWRP 等），合计约 310 MiB。本仓库不把这些二进制塞进版本库，
而是按清单下载、按大小校验、断点续传缓存到：

    assets/shennong_files/

下载源是「镜像链」：按顺序尝试，前一个失败（超时/404/截断）自动换下一个，
任一成功即写盘。顺序 = 显式配置 > 环境变量 > 内置镜像链（Gitee 镜像 →
公益加速前缀 → 直连）：

    [shennong]
    ; 一条完整 base，指定后只走它（会排在链首，失败仍会回落）
    asset_base=https://gitee.com/h-shennong/rom-assets/raw/main/shennong_files/
    ; 或若干加速前缀 / 完整 base，逗号分隔，按序压到链首
    asset_mirrors=https://ghfast.top/,https://gh-proxy.com/

    SHENNONG_ASSET_BASE=...      SHENNONG_ASSET_MIRRORS=...

用法：
    python tools/assets.py list      # 资源 + 缓存状态 + 镜像链
    python tools/assets.py fetch     # 补齐缺失（自动选可用镜像）
    python tools/assets.py fetch fstab.qcom MSA.apk
    python tools/assets.py verify
    python tools/assets.py mirrors   # 只打印镜像链和连通性
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

# --------------------------------------------------------------- 资源来源 / 镜像
# 说明见 NOTICE.md「运行期资源」：这些 URL 只用于下载，资源本身不随本仓库分发，
# 版权与许可见其原始出处。想完全脱离外部源，把资源缓存进 assets/shennong_files/
# 并在 config.ini 里把 asset_base 指到内网/Gitee 镜像即可。
UPSTREAM_ASSET_BASE = (
    "https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/")

# 可选：自己在 Gitee 上导入一份资源镜像（仓库名 rom-assets），国内下载走这条最快
GITEE_OWNER = "h-shennong"
GITEE_MIRROR_REPO = "rom-assets"
GITEE_BASE = "https://gitee.com/{owner}/{repo}/raw/main/shennong_files/".format(
    owner=GITEE_OWNER, repo=GITEE_MIRROR_REPO)

# 公益加速前缀：前缀 + 完整 raw 地址
PROXY_PREFIXES = (
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
)

# 图标包（可选步骤 icons 用）：同样的镜像思路，仓库名见 NOTICE.md
ICON_REPO = "pzcn/Perfect-Icons-Completion-Project"
ICON_BRANCH = "main"


def default_bases():
    """内置镜像链：Gitee 镜像 → 加速前缀 → 直连。"""
    bases = [GITEE_BASE]
    bases += [p + UPSTREAM_ASSET_BASE for p in PROXY_PREFIXES]
    bases.append(UPSTREAM_ASSET_BASE)
    return bases


def _split_list(raw):
    return [x.strip() for x in str(raw or "").replace(";", ",").split(",") if x.strip()]


def _expand(entry):
    """把一条配置展开成完整 base：含 shennong_files/ 视为完整地址，否则当加速前缀。"""
    e = str(entry or "").strip()
    if not e:
        return ""
    if not e.endswith("/"):
        e += "/"
    if "shennong_files/" in e:
        return e
    return e + UPSTREAM_ASSET_BASE


def base_urls(cfg=None):
    """按优先级返回下载源列表（去重、保序）。"""
    cfg = cfg or sc.read_ini()
    sec = cfg.get("sections", {}).get("shennong", {})
    explicit = []
    explicit += _split_list(sec.get("asset_base", ""))
    explicit += _split_list(os.environ.get("SHENNONG_ASSET_BASE", ""))
    explicit += _split_list(sec.get("asset_mirrors", ""))
    explicit += _split_list(os.environ.get("SHENNONG_ASSET_MIRRORS", ""))
    out = []
    for e in explicit:
        u = _expand(e)
        if u and u not in out:
            out.append(u)
    for u in default_bases():
        if u not in out:
            out.append(u)
    return out


def base_url(cfg=None):
    """兼容旧接口：返回第一优先的下载源。"""
    return base_urls(cfg)[0]


def short_base(base):
    """给日志用的短名字，避免一屏 URL。"""
    if base.startswith(GITEE_BASE):
        return "gitee:" + GITEE_MIRROR_REPO
    for p in PROXY_PREFIXES:
        if base.startswith(p):
            return p.strip("/").split("//")[-1]
    if "raw.githubusercontent.com" in base:
        return "github-raw"
    return base


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


def _fetch_one(url, part, size, name, quiet=False, retries=1):
    """从单个 URL 拉到 part（支持断点续传）。返回 (ok, 错误描述)。"""
    offset = part.stat().st_size if part.exists() else 0
    if offset > size:
        try:
            part.unlink()
        except OSError:
            pass
        offset = 0
    if offset == size and size:
        return True, ""
    headers = {"User-Agent": "xmaport-shallow/1.0 (gitee)"}
    if offset:
        headers["Range"] = "bytes={}-".format(offset)
    last = ""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                if offset and getattr(resp, "status", 200) != 206:
                    offset = 0
                mode = "ab" if offset else "wb"
                got = offset
                last_draw = 0.0
                with open(part, mode) as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if not quiet and now - last_draw > 0.5:
                            last_draw = now
                            pct = got * 100.0 / max(size, 1)
                            sys.stdout.write("\r    {:>6.1f}%  {:>10} / {:<10}  {}".format(
                                pct, sc.human(got), sc.human(size), name))
                            sys.stdout.flush()
            if part.stat().st_size == size:
                return True, ""
            last = "大小不符 {} != {}".format(part.stat().st_size, size)
        except urllib.error.HTTPError as e:
            last = "HTTP {}".format(e.code)
            if e.code in (404, 403, 410):
                break
        except Exception as e:                      # noqa: BLE001 - 网络异常种类多
            last = "{}".format(e)
        # 下一轮：重新读取 part 大小决定续传位置
        offset = part.stat().st_size if part.exists() else 0
        if offset >= size and size:
            return True, ""
    return False, last


def _download_one(name, cfg=None, quiet=False):
    size, _use = ASSETS[name]
    dest = local_path(name, cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    errors = []
    for base in base_urls(cfg):
        url = base + urllib.request.quote(name)
        ok, why = _fetch_one(url, part, size, name, quiet=quiet)
        if ok:
            os.replace(part, dest)
            if not quiet:
                sys.stdout.write("\r    [OK] {:>10}  {:<24} <- {}\n".format(
                    sc.human(size), name, short_base(base)))
                sys.stdout.flush()
            return True
        errors.append("{}: {}".format(short_base(base), why))
    if not quiet:
        print("\n    [X] {} 全部镜像失败".format(name))
        for line in errors:
            print("        - {}".format(line))
    return False


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
        print("  镜像链: {}".format(" -> ".join(short_base(b) for b in base_urls(cfg))))
        print("  缓存:   {}".format(asset_dir(cfg)))
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


# ------------------------------------------------------------ 完美图标（icons 步骤）
def icon_urls(cfg=None):
    """图标包 压缩包的镜像链（codeload / Gitee 镜像 / 加速前缀）。"""
    cfg = cfg or sc.read_ini()
    sec = cfg.get("sections", {}).get("shennong", {})
    explicit = _split_list(sec.get("icons_url", ""))
    explicit += _split_list(os.environ.get("SHENNONG_ICONS_URL", ""))
    codeload = "https://codeload.github.com/{repo}/zip/refs/heads/{br}".format(
        repo=ICON_REPO, br=ICON_BRANCH)
    gitee_zip = "https://gitee.com/{owner}/{repo}/repository/archive/{br}.zip".format(
        owner=GITEE_OWNER, repo=ICON_REPO.split("/")[1], br=ICON_BRANCH)
    out = []
    for e in explicit:
        if e and e not in out:
            out.append(e)
    for u in (gitee_zip, codeload,
              "https://ghfast.top/" + codeload,
              "https://gh-proxy.com/" + codeload):
        if u not in out:
            out.append(u)
    return out


def fetch_icons(dest, cfg=None, quiet=False):
    """下载 icons-pack.zip 到 dest；成功返回 True。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for url in icon_urls(cfg):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "xmaport-shallow/1.0 (gitee)"})
            with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
                total = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
            if total > (1 << 20) and zipfile_is_zip(part):
                os.replace(part, dest)
                if not quiet:
                    print("    [OK] icons-pack.zip {} <- {}".format(
                        sc.human(total), short_base(url.split("/zip/")[0] + "/")))
                return True
        except Exception:                            # noqa: BLE001
            continue
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass
    return False


def zipfile_is_zip(path):
    """粗校验：zip 本地文件头 PK\\x03\\x04。"""
    try:
        with open(path, "rb") as f:
            return f.read(4)[:2] == b"PK"
    except OSError:
        return False


# --------------------------------------------------------------------------- 展示
def print_chain(cfg=None, probe=False):
    cfg = cfg or sc.read_ini()
    print()
    print("  资源目录: {}".format(asset_dir(cfg)))
    print("  镜像链（按顺序尝试）:")
    for i, base in enumerate(base_urls(cfg), 1):
        line = "    {}. {:<12} {}".format(i, short_base(base), base)
        print(line)
    if probe:
        print()
        print("  连通性（HEAD 探测 overlay.zip 的首个 1 字节）:")
        for base in base_urls(cfg):
            url = base + "overlay.zip"
            req = urllib.request.Request(url, headers={
                "User-Agent": "xmaport-shallow/1.0 (gitee)", "Range": "bytes=0-0"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    print("    [OK]   {:<12} HTTP {}".format(
                        short_base(base), getattr(r, "status", 200)))
            except urllib.error.HTTPError as e:
                print("    [{}]   {:<12} HTTP {}".format(
                    "~" if e.code in (403, 404) else "X", short_base(base), e.code))
            except Exception as e:                   # noqa: BLE001
                print("    [X]    {:<12} {}".format(short_base(base), e))
    print()


def cmd_list():
    cfg = sc.read_ini()
    d = asset_dir(cfg)
    print_chain(cfg)
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
    ap = argparse.ArgumentParser(description="shennong_files 资源下载器（镜像链 + 断点续传）")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="列出资源与缓存状态")
    p_fetch = sub.add_parser("fetch", help="下载缺失资源")
    p_fetch.add_argument("names", nargs="*", help="只下指定文件（默认全部）")
    sub.add_parser("verify", help="校验大小")
    p_mirrors = sub.add_parser("mirrors", help="打印镜像链，可选连通性探测")
    p_mirrors.add_argument("--probe", action="store_true", help="逐个探测可用性")
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
    if args.cmd == "mirrors":
        print_chain(probe=args.probe)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
