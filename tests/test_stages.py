#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精简 / 修补阶段的无 ROM 回归测试（只用合成数据 + 假资源）

运行：
    python tests/test_stages.py

覆盖：
  * slim.py 的 5 组 make.sh 清单 + media 档位 + 保护名单
  * shennong_patch.py 的资源类步骤（overlay / device_features / displayconfig /
    PowerKeeper / MiAON / camera 拼接 / MSA / bootanimation / fstab / firmware）
  * build.prop 统一（版本号替换、ro.build.user、机型名、vendor 属性）
  * vendor 侧修补（aptX / init.qcom.rc / recovery-from-boot）
"""

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import stage_common as sc          # noqa: E402
import slim                        # noqa: E402
import shennong_patch as sp        # noqa: E402
import assets as asset_mod         # noqa: E402


def write(p, text=""):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def blob(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def zipped(p, members):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


class StageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shennong_test_"))
        self.src = self.tmp / "source_filesystem"
        self.tgt = self.tmp / "target_filesystem"
        self.assets = self.tmp / "assets"
        self.assets.mkdir(parents=True, exist_ok=True)

        # ---- 源分区
        write(self.src / "system" / "build.prop",
              "ro.build.version.incremental=OS4.0.27.0.XEOCNXM\n"
              "ro.system.build.id=OLD_ID\n"
              "ro.build.user=Builder\n"
              "build.date=old\n"
              "build.date.utc=1\n"
              "ro.product.product.name=donor\n")
        blob(self.src / "system" / "app" / "PowerKeeper" / "old.apk", b"o" * 32)
        blob(self.src / "system" / "app" / "Settings" / "Settings.apk", b"s" * 16)
        blob(self.src / "system" / "priv-app" / "BuiltInPrintService" / "x.apk", b"p" * 16)
        blob(self.src / "system" / "priv-app" / "Tag" / "x.apk", b"t" * 16)
        blob(self.src / "system" / "framework" / "services.jar", b"j" * 64)

        blob(self.src / "product" / "app" / "Updater" / "base.apk", b"u" * 16)
        blob(self.src / "product" / "app" / "MSA" / "MSA.apk", b"m" * 8)
        blob(self.src / "product" / "app" / "Settings" / "base.apk", b"k" * 8)
        blob(self.src / "product" / "priv-app" / "AutoRegistration" / "x.apk", b"a" * 8)
        blob(self.src / "product" / "priv-app" / "MiuiCamera" / "MiuiCamera.apk", b"c" * 8)
        blob(self.src / "product" / "data-app" / "MiShop" / "base.apk", b"d" * 16)
        blob(self.src / "product" / "data-app" / "MiuiMusic" / "base.apk", b"e" * 8)
        blob(self.src / "product" / "pangu" / "system" / "priv-app" / "SystemHelper" / "x", b"h" * 8)
        write(self.src / "product" / "etc" / "build.prop",
              "ro.product.build.id=OLD_ID\npersist.miui.density_v2=440\n")
        write(self.src / "product" / "etc" / "device_features" / "old.xml", "<old/>")
        write(self.src / "product" / "etc" / "displayconfig" / "old.xml", "<old/>")
        blob(self.src / "product" / "overlay" / "old.apk", b"o" * 8)
        zipped(self.src / "product" / "media" / "bootanimation.zip",
               {"desc.txt": "old"})
        blob(self.src / "product" / "media" / "wallpaper" / "wp.png", b"w" * 32)
        write(self.src / "system_ext" / "etc" / "build.prop",
              "ro.system_ext.build.id=OLD_ID\n")

        # ---- 目标分区
        write(self.tgt / "odm" / "etc" / "build.prop",
              "ro.product.odm.device=shennong\n")
        write(self.tgt / "vendor" / "build.prop",
              "ro.vendor.build.id=OLD_ID\nro.mi.os.version.incremental=OS3.0.310.0.WNBCNXM\n")
        write(self.tgt / "vendor" / "etc" / "fstab.qcom", "old\n")
        write(self.tgt / "vendor" / "etc" / "init" / "hw" / "init.qcom.rc",
              "on boot\n    start qti-testscripts\n")
        blob(self.tgt / "vendor" / "recovery-from-boot.p", b"r" * 8)
        blob(self.tgt / "vendor" / "bin" / "install-recovery.sh", b"i" * 8)

        # ---- 假资源（大小与 assets.ASSETS 对齐，避免触发下载）
        specs = {
            "overlay.zip": {"new.apk": b"n" * 16},
            "device_features.zip": {"shennong.xml": "<new/>"},
            "displayconfig.zip": {"shennong.xml": "<new/>"},
            "PowerKeeper.zip": {"PowerKeeper.apk": b"P" * 64},
            "MiAONService.apk": b"A" * 32,
            "MSA.apk": b"M" * 16,
            "bootanimation.zip": {"desc.txt": "new"},
            "fstab.qcom": b"# new fstab\n",
            "CameraTools_beta.zip": {"CameraTools/x.apk": b"C" * 16},
            "recovery.zip": {"recovery.img": b"R" * 16},
        }
        for i in (1, 2, 3):
            specs["MiuiCamera.apk.{}".format(i)] = (b"K" * (10 * i))
        sizes = {}
        for name, content in specs.items():
            p = self.assets / name
            if isinstance(content, dict):
                zipped(p, content)
            else:
                blob(p, content)
            sizes[name] = p.stat().st_size
        sizes["MiuiCamera.apk.1"] = 30
        sizes["MiuiCamera.apk.2"] = 30
        sizes["MiuiCamera.apk.3"] = 30
        # 重新写相机分卷，保证拼接结果可断言
        blob(self.assets / "MiuiCamera.apk.1", b"1" * 30)
        blob(self.assets / "MiuiCamera.apk.2", b"2" * 30)
        blob(self.assets / "MiuiCamera.apk.3", b"3" * 30)
        self.sizes = sizes

        # ---- 把模块常量指向临时目录
        self._saved = (sc.SRC_FS, sc.TGT_FS, sc.WORKSPACE, sc.STATE,
                       sc.TGT_UNPACK, asset_mod.ASSETS)
        sc.SRC_FS = self.src
        sc.TGT_FS = self.tgt
        sc.WORKSPACE = self.tmp / "workspace"
        sc.WORKSPACE.mkdir(parents=True, exist_ok=True)
        sc.STATE = sc.WORKSPACE / "slim_state.json"
        sc.TGT_UNPACK = self.tmp / "target_payload"
        sc.TGT_UNPACK.mkdir(parents=True, exist_ok=True)
        asset_mod.ASSETS = {k: (self.sizes[k], "test") for k in self.sizes}

        self.cfg = {
            "flat": {
                "device_platform": "Qualcomm",
                "density": "560",
                "slim_tiers": "media",
                "slim_profile": "shennong",
            },
            "sections": {
                "source": {"url": "https://x/OS4.0.27.0.XEOCNXM/a-ota_full.zip"},
                "target": {"url": "https://x/OS3.0.310.0.WNBCNXM/shennong.zip"},
                "shennong": {"enable": "true", "device": "shennong",
                             "asset_dir": str(self.assets),
                             "steps": "", "enable_signature": "false",
                             "enable_icons": "false"},
            },
        }

    def tearDown(self):
        (sc.SRC_FS, sc.TGT_FS, sc.WORKSPACE, sc.STATE,
         sc.TGT_UNPACK, asset_mod.ASSETS) = self._saved
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    # ------------------------------------------------------------------
    def test_slim_lists(self):
        rc, summary = slim.apply(profile="shennong", tiers=["media"], cfg=self.cfg,
                                 quiet=True)
        self.assertEqual(rc, 0, summary)
        # 清单删除
        self.assertFalse((self.src / "product/app/Updater").exists())
        self.assertFalse((self.src / "product/priv-app/AutoRegistration").exists())
        self.assertFalse((self.src / "system/priv-app/BuiltInPrintService").exists())
        self.assertFalse((self.src / "product/pangu/system/priv-app/SystemHelper").exists())
        # 保护名单：Settings 不被 "system" 关键词误伤
        self.assertTrue((self.src / "product/app/Settings").exists())
        # media 档位（保护名单不拦通用档位）
        self.assertFalse((self.src / "product/media/wallpaper").exists())
        self.assertFalse((self.src / "product/media/bootanimation.zip").exists())
        # data-app 由 preinstall/清单处理：MiShop 命中清单，MiuiMusic 保持
        self.assertFalse((self.src / "product/data-app/MiShop").exists())
        self.assertTrue((self.src / "product/data-app/MiuiMusic").exists())
        state = json.loads(sc.STATE.read_text(encoding="utf-8"))
        self.assertIn("product_app", state["applied"])
        self.assertGreater(state["freed"], 0)

    def test_patch_steps(self):
        rc, summary = sp.run(self.cfg, quiet=True)
        self.assertEqual(rc, 0, [r for r in summary["results"] if r["status"] == "fail"])

        # overlay / device_features / displayconfig
        self.assertTrue((self.src / "product/overlay/new.apk").is_file())
        self.assertFalse((self.src / "product/overlay/old.apk").exists())
        self.assertTrue((self.src / "product/etc/device_features/shennong.xml").is_file())
        self.assertFalse((self.src / "product/etc/device_features/old.xml").exists())

        # PowerKeeper / MiAON / MSA
        self.assertTrue((self.src / "system/app/PowerKeeper/PowerKeeper.apk").is_file())
        self.assertTrue((self.src / "product/app/MiAONService/MiAONService.apk").is_file())
        self.assertTrue((self.src / "product/app/MSA/MSA.apk").is_file())
        self.assertEqual((self.src / "product/app/MSA/MSA.apk").read_bytes(), b"M" * 16)

        # camera：3 个分卷按序拼接
        cam = (self.src / "product/priv-app/MiuiCamera/MiuiCamera.apk").read_bytes()
        self.assertEqual(cam, b"1" * 30 + b"2" * 30 + b"3" * 30)
        self.assertTrue((self.src / "product/app/CameraTools/x.apk").is_file())

        # bootanimation / fstab / firmware
        self.assertEqual((self.src / "product/media/bootanimation.zip").stat().st_size,
                         (self.assets / "bootanimation.zip").stat().st_size)
        self.assertEqual((self.tgt / "vendor/etc/fstab.qcom").read_text(), "# new fstab\n")
        self.assertTrue((sc.TGT_UNPACK / "firmware-update/recovery.img").is_file())

        # build.prop 统一
        sys_bp = (self.src / "system/build.prop").read_text()
        self.assertIn("ro.build.version.incremental=OS3.0.310.0.WNBCNXM", sys_bp)
        self.assertIn("ro.build.user=YuKongA", sys_bp)
        self.assertIn("ro.product.product.name=shennong", sys_bp)
        self.assertIn("ro.system.build.id=OLD_ID", sys_bp)  # 基线相同则不替换
        # vendor 属性
        ven_bp = (self.tgt / "vendor/build.prop").read_text()
        self.assertIn("ro.mi.os.version.incremental=OS4.0.27.0.XEOCNXM", ven_bp)
        self.assertIn("persist.vendor.qcom.bluetooth.aptxadaptiver2_2_support=true", ven_bp)
        # vendor 清理
        self.assertFalse((self.tgt / "vendor/recovery-from-boot.p").exists())
        self.assertNotIn("qti-testscripts", (self.tgt / "vendor/etc/init/hw/init.qcom.rc").read_text())
        # 密度
        self.assertIn("persist.miui.density_v2=560",
                      (self.src / "product/etc/build.prop").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
