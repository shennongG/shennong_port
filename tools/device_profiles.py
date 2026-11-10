# -*- coding: utf-8 -*-
"""设备档案：目标机（14 Pro / shennong）的 super 参数与预算上限

用途：
  * 打包前核对 `device_size`、`metadata`、动态分区组名；
  * 预算 = min(config, 底包实测, 本表) —— 填大了也不会真的按大值打包。

注意：
  * `budget` 是「本次移植允许占用的 super 上限」，来自 参考包的
    `lpmake --device super:8321499136`（7.75 GiB），已在该项目的刷机包上验证；
  * 真机核实方法：`fastboot getvar partition-size:super`，返回值必须 >= budget。
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
        "note": "budget 与分区布局来自 参考包的实机刷机包",
    },
    # 小米 18 Pro Max（移植源，仅记录平台与代号，不参与预算）
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


def normalize(codename):
    return str(codename or "").strip().lower()


def get_profile(codename):
    prof = PROFILES.get(normalize(codename))
    return dict(prof) if prof else None


def list_profiles():
    return sorted(PROFILES.items())
