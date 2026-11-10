#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gitee Release 发布器（替代 GitHub Actions 里的 gh release create）

Gitee 的 Release 与附件走 OpenAPI v5，用个人令牌（私人令牌）鉴权：

    1) Gitee → 设置 → 私人令牌 → 生成新令牌，勾选 projects（仓库读写）即可
    2) 令牌只放环境变量，别写进仓库：

       set GITEE_TOKEN=xxxxxxxxxxxxxxxx
       :: PowerShell
       $env:GITEE_TOKEN = "xxxxxxxxxxxxxxxx"

用法：

    python tools/gitee_release.py list
    python tools/gitee_release.py create --tag sh-20261110-1530 \
        --title "ShennongPort 20261110" --notes-file release/notes.md \
        release/*.7z.001 workspace/output/*.zip

    :: 已有 tag 就先删/换 tag；只想传附件：
    python tools/gitee_release.py upload --tag sh-20261110-1530 release/*.7z.001

    :: 把仓库里某次提交打成 zip 当附件（不走 Release，走仓库归档）：
    python tools/gitee_release.py archive --tag sh-20261110-1530

环境变量：
    GITEE_TOKEN    私人令牌（必需，除了 --help）
    GITEE_REPO     owner/repo，默认 h-shennong/shennong-port
    GITEE_API      API 根，默认 https://gitee.com/api/v5（Gitee 私有化可改）

只依赖标准库：urllib + email 风格 multipart 手工拼装。
"""

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = os.environ.get("GITEE_API", "https://gitee.com/api/v5").rstrip("/")
DEFAULT_REPO = os.environ.get("GITEE_REPO", "h-shennong/shennong-port")

# Gitee 单附件大小上限（企业版 100 MB / 社区版更小），超过就分卷
ATTACH_WARN = 90 * 1024 * 1024


class GiteeError(RuntimeError):
    pass


def _token(cli_token=""):
    tok = (cli_token or os.environ.get("GITEE_TOKEN", "")).strip()
    if not tok:
        raise GiteeError(
            "缺少令牌：set GITEE_TOKEN=... 或 --token（Gitee → 设置 → 私人令牌）")
    return tok


def _request(method, path, token="", params=None, data=None, files=None, timeout=300):
    """发请求；params 走 query（Gitee 的 access_token 习惯放 query）。"""
    params = dict(params or {})
    if token and "access_token" not in params:
        params["access_token"] = token
    url = API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    body = None
    headers = {"User-Agent": "xmaport-shallow-gitee-release/1.0"}
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=UTF-8"
    if files:
        body, headers["Content-Type"] = _multipart(files)

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise GiteeError("{} {} -> HTTP {}: {}".format(method, path, e.code, detail))
    except urllib.error.URLError as e:
        raise GiteeError("{} {} -> 网络错误: {}".format(method, path, e.reason))
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"raw": raw.decode("utf-8", "replace")}


def _multipart(files):
    """files: [(name, path)] → (body, content_type)"""
    boundary = "----xmaport" + uuid.uuid4().hex
    out = bytearray()
    for field, path in files:
        p = Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        with open(p, "rb") as f:
            payload = f.read()
        out += "--{}\r\n".format(boundary).encode()
        out += 'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
            field, p.name).encode("utf-8")
        out += "Content-Type: {}\r\n\r\n".format(ctype).encode()
        out += payload
        out += b"\r\n"
    out += "--{}--\r\n".format(boundary).encode()
    return bytes(out), "multipart/form-data; boundary={}".format(boundary)


# --------------------------------------------------------------------------- 动作
def list_releases(repo, token):
    data = _request("GET", "/repos/{}/releases".format(repo), token,
                    params={"per_page": 30})
    if not isinstance(data, list):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    for r in data:
        print("  {:<24} {:<40} id={}".format(
            r.get("tag_name", ""), (r.get("name") or "")[:40], r.get("id")))
        for a in r.get("assets") or []:
            print("      - {}  {}".format(a.get("name"), a.get("browser_download_url") or ""))
    return 0


def ensure_release(repo, token, tag, title, notes, target="", prerelease=False):
    """有同 tag 就复用，没有就建。返回 release dict。"""
    data = _request("GET", "/repos/{}/releases/tags/{}".format(
        repo, urllib.parse.quote(tag)), token)
    if isinstance(data, dict) and data.get("id"):
        print("  复用已有 Release: {} (id={})".format(tag, data["id"]))
        return data
    payload = {"tag_name": tag, "name": title or tag, "body": notes or tag,
               "prerelease": bool(prerelease)}
    if target:
        payload["target_commitish"] = target
    rel = _request("POST", "/repos/{}/releases".format(repo), token, data=payload)
    if not rel.get("id"):
        raise GiteeError("创建 Release 失败: {}".format(json.dumps(rel, ensure_ascii=False)))
    print("  已创建 Release: {} (id={})".format(tag, rel["id"]))
    return rel


def upload_assets(repo, token, release_id, paths):
    ok = 0
    for path in paths:
        p = Path(path)
        if not p.is_file():
            print("  [X] 文件不存在: {}".format(p))
            continue
        size = p.stat().st_size
        if size > ATTACH_WARN:
            print("  [!] {} 有 {} MiB，Gitee 附件可能拒收；先用 7z -v1900m 分卷".format(
                p.name, size // (1024 * 1024)))
        print("  上传 {} ({:.1f} MiB) ...".format(p.name, size / 1048576.0))
        try:
            data = _request("POST", "/repos/{}/releases/{}/attach_files".format(
                repo, release_id), token, files=[("file", str(p))])
        except GiteeError as e:
            print("  [X] {}".format(e))
            continue
        name = data.get("name") or p.name
        url = data.get("browser_download_url") or data.get("download_url") or ""
        print("  [OK] {}  {}".format(name, url))
        ok += 1
    return ok


def cmd_list(args):
    return list_releases(args.repo, _token(args.token))


def cmd_create(args):
    token = _token(args.token)
    notes = ""
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    elif args.notes:
        notes = args.notes
    rel = ensure_release(args.repo, token, args.tag, args.title, notes,
                         target=args.target, prerelease=args.prerelease)
    files = []
    for pattern in args.files:
        p = Path(pattern)
        if any(ch in pattern for ch in "*?["):
            files += sorted(Path().glob(pattern))
        elif p.exists():
            files.append(p)
    if files:
        n = upload_assets(args.repo, token, rel["id"], [str(f) for f in files])
        print("  附件上传完成: {}/{}".format(n, len(files)))
        return 0 if n == len(files) else 1
    print("  没有附件需要上传")
    return 0


def cmd_upload(args):
    token = _token(args.token)
    data = _request("GET", "/repos/{}/releases/tags/{}".format(
        args.repo, urllib.parse.quote(args.tag)), token)
    if not data.get("id"):
        raise GiteeError("找不到 tag 对应的 Release: {}".format(args.tag))
    files = []
    for pattern in args.files:
        files += sorted(Path().glob(pattern)) if any(
            ch in pattern for ch in "*?[") else [Path(pattern)]
    n = upload_assets(args.repo, token, data["id"], [str(f) for f in files if Path(f).exists()])
    return 0 if n else 1


def cmd_archive(args):
    """把当前提交的仓库归档 zip 拉下来核对（Gitee 归档不需要令牌即可下载）。"""
    url = "https://gitee.com/{}/repository/archive/{}.zip".format(
        args.repo, urllib.parse.quote(args.tag))
    dest = Path(args.out or "release") / "{}.zip".format(args.tag)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("  下载仓库归档: {}".format(url))
    req = urllib.request.Request(url, headers={"User-Agent": "xmaport-shallow"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        total = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    print("  [OK] {} ({:.1f} MiB)".format(dest, total / 1048576.0))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gitee Release 发布器（gh release 的替代）")
    ap.add_argument("--repo", default=DEFAULT_REPO,
                    help="owner/repo，默认 %(default)s")
    ap.add_argument("--token", default="", help="Gitee 私人令牌（默认读 GITEE_TOKEN）")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出 Release")

    p_create = sub.add_parser("create", help="建 Release 并上传附件")
    p_create.add_argument("--tag", required=True)
    p_create.add_argument("--title", default="")
    p_create.add_argument("--notes", default="")
    p_create.add_argument("--notes-file", default="")
    p_create.add_argument("--target", default="", help="target_commitish，默认仓库默认分支")
    p_create.add_argument("--prerelease", action="store_true")
    p_create.add_argument("files", nargs="*")

    p_up = sub.add_parser("upload", help="往已有 Release 追加附件")
    p_up.add_argument("--tag", required=True)
    p_up.add_argument("files", nargs="*")

    p_ar = sub.add_parser("archive", help="下载仓库归档 zip")
    p_ar.add_argument("--tag", required=True)
    p_ar.add_argument("--out", default="release")

    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "create":
        return cmd_create(args)
    if args.cmd == "upload":
        return cmd_upload(args)
    if args.cmd == "archive":
        return cmd_archive(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GiteeError as e:
        print("  [X] {}".format(e))
        sys.exit(1)
