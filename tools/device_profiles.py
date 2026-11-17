# -*- coding: utf-8 -*-
"""设备档案：目标机 / 移植源的 super 参数、预算上限与已验证路线

用途：
  * 打包前核对 `device_size`、`metadata`、动态分区组名；
  * 预算 = min(config, 底包实测, 本表) —— 填大了也不会真的按大值打包；
  * `ROUTES` 记录「哪条移植路线真的刷开过机」，`reference` 指向那一次的基线。

注意：
  * `budget` 是「本次移植允许占用的 super 上限」，来自参考包的
    `lpmake --device super:8321499136`（7.75 GiB），已在该项目的刷机包上验证；
  * 真机核实方法：`fastboot getvar partition-size:super`，返回值必须 >= budget；
  * `nezha → shennong` 这条路线由 `reference/rom6_reference.json`（X-MiPort
    成品包 `X-MiPort_Mi14Pro_OS4.0.7.0.XPACNXM_nezha_*.zip`）校准，见
    docs/PORT_NEZHA_TO_14PRO.md；跑 `python tools\\ref_check.py package <包目录>`
    可以随时复核。
"""

PROFILES = {
    # 小米 14 Pro（移植目标机）
    "shennong": {
        "name": "Xiaomi 14 Pro",
        "platform": "Qualcomm",
        "soc": "SM8650-AB",
        "super_group": "qti_dynamic_partitions",
        "metadata_size": 65536,
        "metadata_slots": 3,
        "virtual_ab": True,
        "budget": 8321499136,          # 7.75 GiB
        "density": 560,
        "refresh_rate": 120,
        "verified": True,
        "note": "budget 与分区布局来自 参考包（Rom6）的实机刷机包",
    },
    # 小米 17 Ultra（移植源 / donor）
    "nezha": {
        "name": "Xiaomi 17 Ultra",
        "platform": "Qualcomm",
        "soc": "SM8850",
        "super_group": "qti_dynamic_partitions",
        "metadata_size": 65536,
        "metadata_slots": 3,
        "virtual_ab": True,
        "budget": 0,
        "verified": False,
        "note": "donor only；HyperOS 4 / Android 17（OS4.0.7.0.XPACNXM）",
    },
    # 小米 18 Pro Max（另一条移植源路线，保留）
    "madrid": {
        "name": "Xiaomi 18 Pro Max",
        "platform": "Qualcomm",
        "soc": "SM8850",
        "super_group": "qti_dynamic_partitions",
        "metadata_size": 65536,
        "metadata_slots": 3,
        "virtual_ab": True,
        "budget": 0,
        "verified": False,
        "note": "donor only",
    },
}

# 迁移路线：source(移植源) -> target(底包/目标机)
#   status = verified   实机刷开过机，有基线可复核
#   status = candidate  同一套流水线可跑，但没有实机验证
ROUTES = {
    ("nezha", "shennong"): {
        "status": "verified",
        "donor_version": "OS4.0.7.0.XPACNXM",
        "base_version": "OS3.0.310.0.WNBCNXM",
        "android_gap": "17 -> 16",
        "reference": "reference/rom6_reference.json",
        "doc": "docs/PORT_NEZHA_TO_14PRO.md",
    },
    ("madrid", "shennong"): {
        "status": "candidate",
        "donor_version": "OS4.0.27.0.XEOCNXM",
        "base_version": "OS3.0.310.0.WNBCNXM",
        "android_gap": "17 -> 16",
        "reference": "reference/rom6_reference.json",
        "doc": "docs/PORT_18PROMAX_TO_14PRO.md",
    },
}


def normalize(codename):
    return str(codename or "").strip().lower()


def get_profile(codename):
    prof = PROFILES.get(normalize(codename))
    return dict(prof) if prof else None


def list_profiles():
    return sorted(PROFILES.items())


def get_route(source, target):
    """返回 (key, route) ；没有登记的路线返回 (key, None)。"""
    key = (normalize(source), normalize(target))
    return key, ROUTES.get(key)


def list_routes():
    return sorted(ROUTES.items(), key=lambda kv: (kv[1].get("status") != "verified", kv[0]))


def verified_routes():
    return [kv for kv in list_routes() if kv[1].get("status") == "verified"]
