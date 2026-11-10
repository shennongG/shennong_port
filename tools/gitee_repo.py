#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gitee 仓库操作（建仓 / 查状态 / 改描述），给 ci/push_to_gitee.ps1 用

Gitee 的 git 推送必须带凭据，而「建仓库」这一步在网页上点也行、用 API 也行。
本脚本把 API 那半截固化下来，令牌只从环境变量或参数读，不落盘。

用法：

    set GITEE_TOKEN=xxxx
    python tools\\gitee_repo.py info   --owner h-shennong --repo XMAPort-SHALLOW
    python tools\\gitee_repo.py create --owner h-shennong --repo XMAPort-SHALLOW ^
        --description "小米 18 Pro Max → 14 Pro 移植流水线" --private
    python tools\\gitee_repo.py ensure --owner h-shennong --repo XMAPort-SHALLOW

`ensure` = 不存在就建（等价 create --if-missing），已存在只打印状态。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("GITEE_API", "https://gitee.com/api/v5").rstrip("/")


def call(method, path, token, params=None, data=None):
    params = dict(params or {})
    if token:
        params["access_token"] = token
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    headers = {"User-Agent": "xmaport-shallow-gitee/1.0"}
    if body:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP {}: {}".format(
            e.code, e.read().decode("utf-8", "replace")[:400]))
    except urllib.error.URLError as e:
        raise RuntimeError("网络错误: {}".format(e.reason))
    return json.loads(raw.decode("utf-8")) if raw else {}


def get_repo(owner, repo, token=""):
    try:
        return call("GET", "/repos/{}/{}".format(owner, repo), token)
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            return None
        raise


def create_repo(owner, repo, token, description="", private=True):
    # /user/repos 建在当前令牌所属账号下；owner 只用来做一致性检查
    me = call("GET", "/user", token)
    if me.get("login") and me["login"].lower() != owner.lower():
        print("  [!] 令牌属于 {}，与目标 owner {} 不一致；仓库会建在 {} 下".format(
            me["login"], owner, me["login"]))
    payload = {
        "name": repo,
        "path": repo,
        "description": description,
        "private": bool(private),
        "auto_init": False,
        "has_issues": True,
        "has_wiki": False,
        "can_comment": True,
    }
    return call("POST", "/user/repos", token, data=payload)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gitee 仓库操作")
    ap.add_argument("--token", default="", help="默认读 GITEE_TOKEN")
    ap.add_argument("--owner", default="h-shennong")
    ap.add_argument("--repo", default="XMAPort-SHALLOW")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("info", help="查仓库是否存在")
    p_c = sub.add_parser("create", help="建仓库")
    p_c.add_argument("--description", default="小米 18 Pro Max → 小米 14 Pro 移植流水线（移植/精简/打包）")
    p_c.add_argument("--public", action="store_true", help="默认私有")
    p_e = sub.add_parser("ensure", help="不存在就建")
    p_e.add_argument("--description", default="小米 18 Pro Max → 小米 14 Pro 移植流水线（移植/精简/打包）")
    p_e.add_argument("--public", action="store_true", help="默认私有")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    token = (args.token or os.environ.get("GITEE_TOKEN", "")).strip()
    if not token and args.cmd in ("create", "ensure"):
        print("  [X] 需要令牌：set GITEE_TOKEN=... 或 --token")
        return 2

    try:
        if args.cmd == "info":
            info = get_repo(args.owner, args.repo, token)
            if not info:
                print("  仓库不存在: {}/{}".format(args.owner, args.repo))
                return 1
            print("  {}/{}  private={}  default_branch={}  size={}".format(
                args.owner, args.repo, info.get("private"),
                info.get("default_branch"), info.get("size")))
            print("  {}".format(info.get("html_url", "")))
            return 0

        if args.cmd == "create":
            info = create_repo(args.owner, args.repo, token,
                               description=args.description,
                               private=not args.public)
            print("  [OK] 已创建 {}  ({})".format(info.get("full_name"), info.get("html_url")))
            return 0

        if args.cmd == "ensure":
            info = get_repo(args.owner, args.repo, token)
            if info:
                print("  已存在: {}  private={}".format(
                    info.get("html_url"), info.get("private")))
                return 0
            print("  不存在，创建中 ...")
            info = create_repo(args.owner, args.repo, token,
                               description=args.description,
                               private=not args.public)
            print("  [OK] 已创建 {}".format(info.get("html_url")))
            return 0
    except RuntimeError as e:
        print("  [X] {}".format(e))
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
