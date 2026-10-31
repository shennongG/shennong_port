# -*- coding: utf-8 -*-
"""合并版流水线的公共设施（移植 / 精简 / 打包 三段共用）

本文件只做四件事，避免三个阶段各写一套：

1. 路径常量：与 XMAPort 原版完全一致（workspace/source_filesystem 等），
   这样「移植」阶段产出的工作区可以直接交给「精简」和「打包」。
2. 配置读取：config.ini 同时兼容 GBK / UTF-8，既返回「扁平键」也返回
   「section.key」两种写法，精简段新增的键不会和老配置冲突。
3. 分区根定位：XMAPort 解包出的 system 分区有时会多一层 system/ 目录
   （Android 11+ system_root 镜像），这里统一探测出「内容根」。
4. 小工具：人类可读体积、bool 解析、安全删除（不跟随 junction/符号链接）。

只依赖标准库。
"""

import fnmatch
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
WORKSPACE = ROOT / "workspace"
SRC_FS = WORKSPACE / "source_filesystem"
TGT_FS = WORKSPACE / "target_filesystem"
SRC_UNPACK = WORKSPACE / "source_payload"
TGT_UNPACK = WORKSPACE / "target_payload"
SRC_ROM = WORKSPACE / "source_rom"
TGT_ROM = WORKSPACE / "target_rom"
PACK_OUT = WORKSPACE / "packed"
OUT_DIR = WORKSPACE / "output"
ASSETS = ROOT / "assets"
SHENNONG_ASSETS = ASSETS / "shennong_files"
CONFIG = ROOT / "config.ini"
STATE = WORKSPACE / "slim_state.json"

# super 里会被打进 super.img 的分区（顺序即 lpmake 里的顺序）
SUPER_PARTS = ("system", "system_ext", "product", "odm", "mi_ext",
               "vendor", "vendor_dlkm", "system_dlkm")
# 允许精简内容的分区：只限「移植过来的源分区」
SLIM_PARTS = ("system", "system_ext", "product")


# --------------------------------------------------------------------------- 配置
def read_ini(path=None):
    """读取 config.ini，返回 {"flat": {...}, "sections": {name: {...}}}。

    * 编码：UTF-8（可带 BOM）优先，失败回落 GBK —— 两个上游项目一个用 GBK
      一个用 UTF-8，这里必须都吃。
    * 键统一小写；`[source] url=` 在 flat 里会互相覆盖，所以 source/target
      的 url 请用 sections["source"]["url"] 读取。
    """
    p = Path(path) if path else CONFIG
    flat = {}
    sections = {}
    try:
        raw = p.read_bytes()
    except OSError:
        return {"flat": flat, "sections": sections}
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = None
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("gbk", errors="ignore")

    section = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(";") or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip().lower()
            sections.setdefault(section, {})
            continue
        if "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip().lower()
        val = val.strip()
        flat[key] = val
        if section:
            sections.setdefault(section, {})[key] = val
    return {"flat": flat, "sections": sections}


def cfg_get(cfg, key, default=""):
    """按优先级取配置：section.key（若给了 section）由调用方处理。"""
    val = cfg.get("flat", {}).get(key)
    return default if val is None or val == "" else val


def cfg_int(cfg, key, default):
    try:
        return int(str(cfg.get("flat", {}).get(key, "")).strip())
    except Exception:
        return default


def cfg_bool(cfg, key, default=False):
    raw = str(cfg.get("flat", {}).get(key, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")


# --------------------------------------------------------------------------- 体积
def human(num):
    try:
        v = float(num)
    except Exception:
        return "?"
    neg = "-" if v < 0 else ""
    v = abs(v)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if v < 1024.0 or unit == "TiB":
            if unit == "B":
                return "{}{:.0f} B".format(neg, v)
            return "{}{:.2f} {}".format(neg, v, unit)
        v /= 1024.0
    return "?"


# --------------------------------------------------------------------------- 文件
def long_path(path):
    """Windows 长路径前缀，避免超深目录删不掉。"""
    p = os.path.abspath(str(path))
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + p
    return p


def is_reparse(path):
    """Windows junction / 符号链接：删目录时不能跟进去。"""
    try:
        if os.path.islink(path):
            return True
        if os.name == "nt":
            st = os.stat(path, follow_symlinks=False)
            return bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except OSError:
        return False
    return False


def path_size(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def remove_path(path):
    """删文件/目录；目录不跟随链接。返回 True 表示已不存在。"""
    p = long_path(path)
    try:
        if os.path.isdir(p) and not is_reparse(path):
            shutil.rmtree(p, ignore_errors=True)
            return not os.path.exists(p)
        os.remove(p)
        return not os.path.exists(p)
    except Exception:
        return False


def write_state(payload):
    try:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception as e:
        print("  [slim] 写 slim_state.json 失败: {}".format(e))


def read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------------------- 分区
def content_root(part):
    """返回分区的「内容根」：SRC_FS/<part> 或 SRC_FS/<part>/<part>。

    判据：内层目录里能看到 etc/ 这种分区标志目录，而外层看不到。
    """
    base = SRC_FS / part
    if not base.is_dir():
        return base
    inner = base / part
    if inner.is_dir() and (inner / "etc").is_dir() and not (base / "etc").is_dir():
        return inner
    return base


def target_content_root(part):
    base = TGT_FS / part
    if not base.is_dir():
        return base
    inner = base / part
    if inner.is_dir() and (inner / "etc").is_dir() and not (base / "etc").is_dir():
        return inner
    return base


def find_part_dir(part, prefer_target=False):
    """在源/目标工作区里找分区内容根；找不到返回 None。"""
    order = (target_content_root, content_root) if prefer_target else (content_root, target_content_root)
    for fn in order:
        p = fn(part)
        if p.is_dir():
            return p
    return None


def iter_dirs(root):
    """遍历目录树（含自身），产出 (dirpath, name)。"""
    if not root or not os.path.isdir(str(root)):
        return
    for cur, dirs, _files in os.walk(str(root)):
        for d in list(dirs):
            yield os.path.join(cur, d), d


def matches_keep(rel, keep_globs):
    rel = rel.replace("\\", "/").lower()
    for pat in keep_globs:
        pat = pat.strip().lower().replace("\\", "/")
        if not pat:
            continue
        if fnmatch.fnmatchcase(rel, pat) or fnmatch.fnmatchcase(rel + "/", pat):
            return True
        # 保护目录时把子路径一起保护
        if fnmatch.fnmatchcase(rel + "/x", pat + "/*"):
            return True
    return False


def stash(path, stash_root, part):
    """不删除，移动到 workspace/.slim_stash/<part>/... 便于回滚。"""
    try:
        rel = os.path.relpath(path, str(content_root(part)))
    except Exception:
        rel = os.path.basename(path)
    dest = Path(stash_root) / part / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(long_path(path), str(dest))
        return True
    except Exception:
        return False


def timestamp():
    return int(time.time())


def main_guard(fn):
    """统一 stdout 编码，避免 Windows 管道下中文崩。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return fn()
