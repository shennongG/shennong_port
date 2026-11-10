#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一套极小的合成工作区，用于无 ROM 端到端测试（精简 -> 修补 -> 打包）。

    python tests/make_fixture.py

会在项目根目录创建 workspace/，里面是假的 system/product/vendor 树、
payload 镜像、fs_config/file_contexts。之后可以直接：

    python shennong_port.py --auto --stage slim --device shennong --offline
    python shennong_port.py --auto --stage pack --device shennong
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "workspace"

for d in ("source_filesystem", "target_filesystem", "source_payload",
          "target_payload", "packed", "output", "source_rom", "target_rom",
          "download_source", "download_target"):
    (WS / d).mkdir(parents=True, exist_ok=True)

SRC = WS / "source_filesystem"
TGT = WS / "target_filesystem"


def write(p, text=""):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def blob(p, data=b"x" * 16):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# ---------------------------------------------------------------- 源 system
write(SRC / "system" / "build.prop", """ro.build.version.incremental=OS4.0.27.0.XEOCNXM
ro.build.version.security_patch=2026-08-01
ro.system.build.id=BP2A.260701.001
ro.build.user=Builder
ro.product.product.name=madrid
build.date=2026-07-01
build.date.utc=1782864000
""")
blob(SRC / "system" / "app" / "PowerKeeper" / "PowerKeeper.apk", b"P" * 4096)
blob(SRC / "system" / "app" / "Settings" / "Settings.apk", b"S" * 2048)
blob(SRC / "system" / "priv-app" / "BuiltInPrintService" / "x.apk", b"p" * 1024)
blob(SRC / "system" / "priv-app" / "Tag" / "x.apk", b"t" * 1024)
blob(SRC / "system" / "priv-app" / "SystemUI" / "SystemUI.apk", b"U" * 2048)
blob(SRC / "system" / "framework" / "services.jar", b"j" * (64 * 1024))

# ---------------------------------------------------------------- 源 product
write(SRC / "product" / "etc" / "build.prop",
      "ro.product.build.id=BP2A.260701.001\npersist.miui.density_v2=440\n")
for app in ("MiShop", "MIUIYoupin", "MIUIHuanJi", "Health", "MIService",
            "MIUIVideo", "MiuiMusic"):
    blob(SRC / "product" / "data-app" / app / "base.apk", b"d" * 4096)
for app in ("PaymentService", "Updater", "MIUIgreenguard", "Settings"):
    blob(SRC / "product" / "app" / app / "base.apk", b"a" * 2048)
blob(SRC / "product" / "pangu" / "system" / "priv-app" / "SystemHelper" / "x.apk", b"h" * 1024)
blob(SRC / "product" / "priv-app" / "AutoRegistration" / "x.apk", b"r" * 1024)
blob(SRC / "product" / "priv-app" / "MiuiCamera" / "MiuiCamera.apk", b"C" * 4096)
blob(SRC / "product" / "app" / "MSA" / "MSA.apk", b"M" * 512)
write(SRC / "product" / "etc" / "device_features" / "old.xml", "<old/>")
write(SRC / "product" / "etc" / "displayconfig" / "old.xml", "<old/>")
blob(SRC / "product" / "overlay" / "old.apk", b"o" * 512)
(SRC / "product" / "media").mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(SRC / "product" / "media" / "bootanimation.zip", "w") as z:
    z.writestr("desc.txt", "1080 2400 30\n")
blob(SRC / "product" / "media" / "theme" / "default" / "icons", b"i" * 256)
blob(SRC / "product" / "media" / "wallpaper" / "wp.png", b"w" * 8192)

write(SRC / "system_ext" / "etc" / "build.prop",
      "ro.system_ext.build.id=BP2A.260701.001\n")

cfg = SRC / "config"
cfg.mkdir(parents=True, exist_ok=True)
for part in ("system", "system_ext", "product"):
    write(cfg / (part + "_fs_config"), "{} 0 0 0755\n".format(part))
    write(cfg / (part + "_file_contexts"),
          "/{}(/.*)? u:object_r:{}_file:s0\n".format(part, part))

# ---------------------------------------------------------------- 目标 odm/vendor
write(TGT / "odm" / "etc" / "build.prop",
      "ro.product.odm.device=shennong\nro.odm.build.id=BP2A.260701.001\n")
blob(TGT / "odm" / "etc" / "x.bin", b"x" * 256)
write(TGT / "vendor" / "build.prop",
      "ro.vendor.build.id=BP2A.260701.001\n"
      "ro.mi.os.version.incremental=OS3.0.310.0.WNBCNXM\n")
write(TGT / "vendor" / "etc" / "fstab.qcom", "old-fstab\n")
write(TGT / "vendor" / "etc" / "init" / "hw" / "init.qcom.rc",
      "on boot\n    start qti-testscripts\n    start other\n")
blob(TGT / "vendor" / "recovery-from-boot.p", b"r" * 128)
blob(TGT / "vendor" / "bin" / "install-recovery.sh", b"i" * 128)
blob(TGT / "vendor" / "lib64" / "libfoo.so", b"l" * 512)
write(TGT / "config" / "vendor_fs_config", "vendor 0 0 0755\n")
write(TGT / "config" / "vendor_file_contexts", "/vendor(/.*)? u:object_r:vendor_file:s0\n")
write(TGT / "config" / "odm_fs_config", "odm 0 0 0755\n")
write(TGT / "config" / "odm_file_contexts", "/odm(/.*)? u:object_r:vendor_file:s0\n")

# ---------------------------------------------------------------- payload
for name in ("mi_ext.img", "vendor.img", "system_dlkm.img"):
    (WS / "target_payload" / name).write_bytes(b"\x00" * 4096)
(WS / "source_payload" / "mi_ext.img").write_bytes(b"\x11" * 4096)
for name in ("boot.img", "dtbo.img", "vbmeta.img"):
    (WS / "target_payload" / name).write_bytes(b"\x22" * 2048)

write(WS / "config.txt", "TARGET_DEVICE=shennong\n")
print("fixture ready:", WS)
