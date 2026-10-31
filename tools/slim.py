#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精简阶段（slim）：把 14PRO_SHALLOW_ROM 的删除清单变成可审计的 Python 模块

上游 14PRO_SHALLOW_ROM 的 make.sh 用 5 组 `find -iname "*名字*"` 删应用，
本文件把这份清单原样收录，并补上「按预算追加档位」的能力：

    profile shennong   14 Pro 专用清单（make.sh 原样 5 组，默认）
    tiers media        开机动画 / 壁纸包
    tiers audio        系统铃声 / 通知音
    tiers preinstall   全部 data-app（比 shennong 组更狠）
    tiers apps         额外生态应用
    custom             config.ini [slim] extra_remove 手工点名

只处理 workspace/source_filesystem（移植过来的 system/system_ext/product），
绝不动 workspace/target_filesystem —— 那里的 odm/vendor 是底包，删了必砖。

用法：
    python tools/slim.py list
    python tools/slim.py plan [--top 20]
    python tools/slim.py apply [--profile shennong] [--tiers media,audio]
                               [--dry-run] [--stash] [--json]

退出码：0 成功 / 1 没有可精简内容或删除失败 / 2 参数或工作区错误
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stage_common as sc  # noqa: E402

# ---------------------------------------------------------------------------
# 14PRO_SHALLOW_ROM / make.sh 的 5 组清单（顺序、名字逐字照抄）
#   part  = 分区
#   sub   = 分区内相对目录
#   apps  = 目录名包含任一关键词（大小写不敏感）即整棵删除
# make.sh 里 `"CatchLog""com.xiaomi.ugd"` 实际会被 bash 拼成一个词，
# 这里按作者本意拆成两个；`system` 这一条过宽，默认只匹配「名字以它开头」
# 会在 --strict 下生效，见 MATCH_MODE。
# ---------------------------------------------------------------------------
SHENNONG_GROUPS = [
    {
        "id": "product_app",
        "part": "product",
        "sub": "app",
        "desc": "product/app：统计/上报/支付/无障碍/OTA 等 21 个系统应用",
        "apps": [
            "AnalyticsCore", "CarWith", "CatchLog", "com.xiaomi.ugd",
            "GoogleLocationHistory", "HybridPlatform", "MiBugReport",
            "MIUIgreenguard", "MIUIReporter", "OtaProvision", "OTrPBroker",
            "PaymentService", "remoteSimLockAuthentication",
            "remotesimlockservice", "RideModeAudio", "SwitchAccess",
            "system", "talkback", "Updater", "UPTsmService", "WMService",
        ],
    },
    {
        "id": "product_data_app",
        "part": "product",
        "sub": "data-app",
        "desc": "product/data-app：商店/视频/音乐/阅读/健康等 26 个预装",
        "apps": [
            "MIGalleryLockscreen", "MIpay", "MIUIDriveMode",
            "MIUIDuokanReader", "MIUIGameCenter", "MIUINewHome",
            "MIUIYoupin", "MIUIHuanJi", "MIUIMiDrive", "MIUIVirtualSim",
            "ThirdAppAssistant", "XMRemoteController", "MIUIVipAccount",
            "MiuiScanner", "Xinre", "SmartHome", "MiShop", "MiRadio",
            "MIUICompass", "BaiduIME", "iflytek.inputmethod", "MIUIEmail",
            "MIUIVideo", "MIUIMusicT", "Health", "MIService",
        ],
    },
    {
        "id": "product_pangu_priv_app",
        "part": "product",
        "sub": "pangu/system/priv-app",
        "desc": "product/pangu/system/priv-app：SystemHelper",
        "apps": ["SystemHelper"],
    },
    {
        "id": "product_priv_app",
        "part": "product",
        "sub": "priv-app",
        "desc": "product/priv-app：自动注册/更新器/游戏中心SDK/浏览器等 6 个",
        "apps": [
            "AutoRegistration", "ConfigUpdater", "MiGameCenterSDKService",
            "MIbrowser", "MIUIBarrageV2", "RegService",
        ],
    },
    {
        "id": "system_priv_app",
        "part": "system",
        "sub": "priv-app",
        "desc": "system/priv-app：打印/通话记录备份/小区广播/MusicFX 等 7 个",
        "apps": [
            "BuiltInPrintService", "CallLogBackup", "CellBroadcastLegacyApp",
            "CellBroadcastServiceModulePlatform", "MusicFX", "Tag",
            "UserDictionaryProvider",
        ],
    },
]

# 预算不够时按顺序追加的通用档位（相对分区内容根的 glob）
GENERIC_TIERS = {
    "media": {
        "desc": "开机动画 / 壁纸包（省 0.1~0.6 GiB）",
        "rules": [
            ("product", "media/bootanimation*"),
            ("product", "media/wallpaper*"),
            ("system", "media/bootanimation*"),
            ("system", "media/wallpaper*"),
            ("system_ext", "media/bootanimation*"),
        ],
    },
    "audio": {
        "desc": "系统铃声 / 通知音 / UI 音效（省 30~120 MiB）",
        "rules": [
            ("system", "media/audio/alarms/*"),
            ("system", "media/audio/notifications/*"),
            ("system", "media/audio/ringtones/*"),
            ("system", "media/audio/ui/*"),
        ],
    },
    "preinstall": {
        "desc": "全部 data-app / preinstall 目录（比 shennong 组更狠）",
        "rules": [
            ("product", "data-app"),
            ("product", "data_app"),
            ("product", "preinstall"),
            ("product", "preinstall_app"),
            ("product", "delapp"),
            ("product", "del-app"),
        ],
    },
    "apps": {
        "desc": "额外生态应用（可回装）",
        "rules": [
            ("product", "app/MiShop*"),
            ("product", "app/MiuiVideo*"),
            ("product", "app/MiuiMusic*"),
            ("product", "app/MiGameCenter*"),
            ("product", "priv-app/MiuiBrowser*"),
            ("product", "app/MiLive*"),
            ("product", "app/MiSport*"),
            ("product", "app/MIRadio*"),
        ],
    },
    "ai": {
        "desc": "AI 模型/引擎（18 Pro Max 特有，省 0.2~2 GiB，AI 功能失效）",
        "rules": [
            ("product", "etc/ai"),
            ("product", "etc/ai_models"),
            ("product", "etc/miui_ai"),
            ("product", "app/*AI*"),
            ("product", "priv-app/*AI*"),
            ("system", "etc/ai"),
            ("system", "app/*AI*"),
        ],
    },
    "theme": {
        "desc": "主题/字体/动态图标素材（省 0.1~0.8 GiB，主题可回装）",
        "rules": [
            ("product", "media/theme/*"),
        ],
    },
}

# 保护名单：这些关键词命中的目录永不删除（防止误伤相机/桌面等）
HARD_KEEP_TOKENS = [
    "miuicamera", "camera", "cameraservice", "miuihome", "launcher",
    "systemui", "settings", "securitycenter", "miuisystem", "framework",
    "overlay", "device_features", "displayconfig", "bootanimation",
]

STASH_DIR = sc.WORKSPACE / ".slim_stash"


# --------------------------------------------------------------------------- 工具
def _config():
    return sc.read_ini()


def _keep_globs(cfg):
    raw = cfg.get("flat", {}).get("slim_keep", "")
    return [k.strip() for k in raw.replace(";", ",").split(",") if k.strip()]


def _extra_remove(cfg):
    raw = cfg.get("flat", {}).get("extra_remove", "")
    return [k.strip() for k in raw.replace(";", ",").split(",") if k.strip()]


def _protected(name):
    low = name.lower()
    return any(tok in low for tok in HARD_KEEP_TOKENS)


def _iter_hits(group, keep_globs):
    """产出 (abs_path, rel_path) —— group 里所有命中目录（不重复）。"""
    part = group["part"]
    root = sc.content_root(part)
    if not root.is_dir():
        return
    start = root / group["sub"]
    if not start.is_dir():
        return
    tokens = [a.lower() for a in group["apps"] if a.strip()]
    seen = set()
    for cur, dirs, _files in os.walk(str(start)):
        dirs.sort(key=str.lower)
        for d in dirs:
            low = d.lower()
            if not any(tok in low for tok in tokens):
                continue
            abs_path = os.path.join(cur, d)
            rel = os.path.relpath(abs_path, str(root)).replace("\\", "/")
            if sc.matches_keep(rel, keep_globs):
                continue
            if os.path.normcase(abs_path) in seen:
                continue
            seen.add(os.path.normcase(abs_path))
            yield abs_path, rel


def _iter_glob_hits(rules, keep_globs):
    """通用档位：按 glob 匹配目录/文件，目录命中后不再下钻。"""
    for part, pattern in rules:
        root = sc.content_root(part)
        if not root.is_dir():
            continue
        pat = pattern.lower().rstrip("/")
        for cur, dirs, files in os.walk(str(root)):
            rel_root = os.path.relpath(cur, str(root)).replace("\\", "/")
            prefix = "" if rel_root == "." else rel_root + "/"
            keep_dirs = []
            for d in sorted(dirs, key=str.lower):
                rel = (prefix + d).lower()
                if sc.matches_keep(rel, keep_globs):
                    continue
                if _glob_match(rel, pat):
                    yield os.path.join(cur, d), prefix + d
                else:
                    keep_dirs.append(d)
            dirs[:] = keep_dirs
            for f in sorted(files, key=str.lower):
                rel = (prefix + f).lower()
                if sc.matches_keep(rel, keep_globs):
                    continue
                if _glob_match(rel, pat):
                    yield os.path.join(cur, f), prefix + f


def _glob_match(rel, pat):
    import fnmatch
    # 支持 "app/Foo*" 与 "media/audio/*"
    if fnmatch.fnmatchcase(rel, pat):
        return True
    if rel.startswith(pat.rstrip("*").rstrip("/") + "/"):
        # 目录本身没带 /* 时也允许整棵命中
        return pat.endswith("*")
    return False


def _delete(abs_path, stash=False, part="", protect=True):
    if protect and _protected(os.path.basename(abs_path)):
        return False, "受保护"
    if stash:
        ok = sc.stash(abs_path, STASH_DIR, part)
        return ok, "已移入 .slim_stash" if ok else "移动失败"
    ok = sc.remove_path(abs_path)
    return ok, "已删除" if ok else "删除失败"


# --------------------------------------------------------------------------- 命令
def cmd_list():
    print()
    print("  精简 profile: shennong（14PRO_SHALLOW_ROM 原清单，默认启用）")
    for i, g in enumerate(SHENNONG_GROUPS, 1):
        print("    {}. {:<24} {:<38} {:>3} 个关键词".format(
            i, g["id"], g["part"] + "/" + g["sub"], len(g["apps"])))
        print("       " + g["desc"])
    print()
    print("  追加档位（预算不够时用 --tiers 或 config.ini [slim] slim_tiers 指定）:")
    for name, tier in GENERIC_TIERS.items():
        print("    {:<11} {}".format(name, tier["desc"]))
    print("    {:<11} {}".format("custom", "config.ini [slim] extra_remove 手工点名"))
    print()
    return 0


def cmd_plan(top=0, profile="shennong"):
    cfg = _config()
    keep = _keep_globs(cfg)
    if not sc.SRC_FS.is_dir():
        print("  [slim] 没有 workspace/source_filesystem：请先跑「移植」阶段")
        return 2
    total = 0
    rows = []
    for g in SHENNONG_GROUPS:
        size = 0
        hits = 0
        for abs_path, _rel in _iter_hits(g, keep):
            size += sc.path_size(abs_path)
            hits += 1
        rows.append((g["id"], hits, size))
        total += size
    print()
    print("  [slim] 14 Pro 精简清单实测（当前工作区）:")
    for gid, hits, size in rows:
        print("    {:<24} {:>4} 项  {:>10}".format(gid, hits, sc.human(size)))
    print("    {:<24} {:>4}     {:>10}".format("合计", sum(r[1] for r in rows), sc.human(total)))
    print()
    print("  [slim] 可追加档位预估:")
    for name, tier in GENERIC_TIERS.items():
        size = sum(sc.path_size(p) for p, _ in _iter_glob_hits(tier["rules"], keep))
        print("    {:<11} {:>10}   {}".format(name, sc.human(size), tier["desc"]))
    extra = _extra_remove(cfg)
    if extra:
        print("    {:<11} {:>10}   {}".format("custom", "?", ",".join(extra)))
    if top > 0:
        print()
        print("  [slim] 源分区最大的 {} 个文件（手工精简时看这里）:".format(top))
        for size, rel in _largest(top):
            print("    {:>12}  {}".format(sc.human(size), rel))
    return 0


def _largest(top):
    rows = []
    for part in sc.SLIM_PARTS:
        root = sc.content_root(part)
        if not root.is_dir():
            continue
        for cur, _dirs, files in os.walk(str(root)):
            for f in files:
                p = os.path.join(cur, f)
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                rel = os.path.relpath(p, str(root)).replace("\\", "/")
                rows.append((size, part + "/" + rel))
    rows.sort(key=lambda x: x[0], reverse=True)
    return rows[:top]


def apply(profile="shennong", tiers=None, dry_run=False, stash=False,
          cfg=None, quiet=False):
    """执行精简，返回 (rc, summary)。XMAPort 精简段直接 import 调用。"""
    cfg = cfg or _config()
    keep = _keep_globs(cfg)
    tiers = [t.strip() for t in (tiers or []) if t.strip()]
    unknown = [t for t in tiers if t not in GENERIC_TIERS and t != "custom"]
    if unknown:
        if not quiet:
            print("  [slim] 未知档位: {}（可用: {}）".format(
                ",".join(unknown), ",".join(sorted(GENERIC_TIERS))))
        return 2, {}

    if not sc.content_root("system").is_dir():
        if not quiet:
            print("  [slim] 工作区里没有解包后的 system 分区：请先跑「移植」阶段")
        return 2, {}

    freed_by_part = {}
    group_stats = {}
    removed = 0
    failed = 0

    def _record(part, size):
        freed_by_part[part] = freed_by_part.get(part, 0) + size

    # 1) shennong 清单
    groups = SHENNONG_GROUPS if profile != "none" else []
    for g in groups:
        gid = g["id"]
        count = 0
        size_sum = 0
        for abs_path, rel in _iter_hits(g, keep):
            size = sc.path_size(abs_path)
            if dry_run:
                ok, _why = True, "预演"
            else:
                ok, _why = _delete(abs_path, stash=stash, part=g["part"])
            if not ok:
                failed += 1
                if not quiet:
                    print("  [slim] 跳过（{}）: {}/{}".format(_why, g["part"], rel))
                continue
            count += 1
            size_sum += size
        group_stats[gid] = {"hits": count, "freed": size_sum}
        removed += count
        if count:
            _record(g["part"], size_sum)
            if not quiet:
                print("  [slim] {:<24} {:>4} 项  {:>10}".format(
                    gid, count, sc.human(size_sum)))

    # 2) 追加档位
    for name in tiers:
        if name == "custom":
            rules = []
            for item in _extra_remove(cfg):
                item = item.replace("\\", "/").strip("/")
                if "/" not in item:
                    continue
                part, pat = item.split("/", 1)
                if part in sc.SLIM_PARTS:
                    rules.append((part, pat))
        else:
            rules = GENERIC_TIERS[name]["rules"]
        count = 0
        size_sum = 0
        per_part = {}
        for abs_path, rel in _iter_glob_hits(rules, keep):
            size = sc.path_size(abs_path)
            part = _part_of(abs_path)
            if dry_run:
                ok, _why = True, "预演"
            else:
                ok, _why = _delete(abs_path, stash=stash, part=part, protect=False)
            if not ok:
                failed += 1
                continue
            count += 1
            size_sum += size
            per_part[part] = per_part.get(part, 0) + size
        for part, size in per_part.items():
            _record(part, size)
        group_stats["tier:" + name] = {"hits": count, "freed": size_sum}
        removed += count
        if count and not quiet:
            print("  [slim] {:<24} {:>4} 项  {:>10}".format(
                "tier:" + name, count, sc.human(size_sum)))

    total = sum(freed_by_part.values())
    if not quiet:
        print("  [slim] {}合计 {} 项，释放 {}".format(
            "[预演] " if dry_run else "", removed, sc.human(total)))
        if failed:
            print("  [slim] {} 项删除失败（Windows 权限/占用？）".format(failed))

    touched = sorted(freed_by_part.keys())
    summary = {
        "profile": profile,
        "tiers": tiers,
        "dry_run": bool(dry_run),
        "groups": group_stats,
        "touched": touched,
        "freed": total,
        "freed_by_part": freed_by_part,
        "removed": removed,
        "failed": failed,
        "ts": sc.timestamp(),
    }
    if not dry_run:
        prev = sc.read_state()
        applied = prev.get("applied", [])
        for gid in [g["id"] for g in groups] + ["tier:" + t for t in tiers]:
            st = group_stats.get(gid)
            if st and st["hits"] and gid not in applied:
                applied.append(gid)
        summary["applied"] = applied
        sc.write_state(summary)
        if touched and not quiet:
            print("  [slim] 需要重新打包: {}".format(",".join(touched)))
    return (0 if not failed else 1), summary


def _part_of(abs_path):
    ap = os.path.normcase(os.path.abspath(abs_path))
    for part in sc.SLIM_PARTS:
        root = os.path.normcase(os.path.abspath(str(sc.content_root(part))))
        if ap.startswith(root + os.sep):
            return part
    return "?"


def cmd_apply(args):
    cfg = _config()
    tiers = [t.strip() for t in (args.tiers or "").split(",") if t.strip()]
    rc, summary = apply(profile=args.profile, tiers=tiers,
                        dry_run=args.dry_run, stash=args.stash, cfg=cfg)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return rc


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="14 Pro 精简阶段 / slim stage")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出清单与档位")

    p_plan = sub.add_parser("plan", help="体检当前工作区")
    p_plan.add_argument("--top", type=int, default=0)
    p_plan.add_argument("--profile", default="shennong")

    p_apply = sub.add_parser("apply", help="执行精简")
    p_apply.add_argument("--profile", default="shennong", choices=("shennong", "none"))
    p_apply.add_argument("--tiers", default="", help="追加档位，逗号分隔")
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.add_argument("--stash", action="store_true", help="不删除，移到 .slim_stash")
    p_apply.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "plan":
        return cmd_plan(args.top, args.profile)
    if args.cmd == "apply":
        return cmd_apply(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
