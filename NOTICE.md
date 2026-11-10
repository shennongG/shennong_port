# NOTICE — 第三方代码、二进制与许可证

本文件是本仓库及其发行物（源码包、卡刷包）**唯一的第三方声明入口**。
项目主体按 MIT 发布（见 [LICENSE](LICENSE)）；下面列出的组件另有其权利人，
使用、复制、再分发时以各自的许可证为准。

---

## 1. 代码来源

| 范围 | 来源 | 许可证 |
| --- | --- | --- |
| 移植 / 解包 / 分区迁移 / super 合成（早期版本，现由本项目维护） | XMAPort，Copyright (c) 2025 NorthStarK-Lvy | MIT（全文见 `LICENSE`，其版权行在此保留） |
| 14 Pro 精简清单与功能修补的**行为规格**（按公开行为重新实现，未复制其代码） | 14PRO_SHALLOW_ROM，Copyright (c) 2025 XHR222 | 未声明许可证；本仓库不包含其代码或二进制 |
| 本仓库其余部分（流水线编排、精简/修补实现、打包、Gitee 适配、CI） | ShennongPort contributors | MIT |

> MIT 要求保留版权声明与许可声明。上游移植引擎的版权行与 MIT 全文均已随本仓库
> 分发（`LICENSE`），因此义务已履行；本项目**不主张**对上述上游代码的著作权。

---

## 2. 运行期下载的资源（不随本仓库分发）

`tools/assets.py` 会按清单从公开地址拉取 14 Pro 专属资源（相机 / overlay /
device_features / displayconfig / fstab / TWRP 等，约 310 MiB）到
`assets/shennong_files/`。

* 这些文件**不进入**本仓库的版本库，也不随源码包或卡刷包分发；
* 版权归其原始权利人，本仓库只提供下载与校验脚本；
* 默认下载基址：`tools/assets.py` 中的 `UPSTREAM_ASSET_BASE`，
  可用 `config.ini` 的 `asset_base` / `asset_mirrors` 或环境变量
  `SHENNONG_ASSET_BASE` 指向自有镜像；
* 可选图标包（`icons` 步骤）同样只在运行时下载，不随仓库分发。

如果你要**再分发**这些资源，需自行取得权利人许可。

---

## 3. 随包分发的第三方可执行文件

`tools/` 下的二进制原样分发（未修改），清单如下。许可证正文见
[`licenses/`](licenses/)。

| 组件 | 文件 | 许可证 | 正文 |
| --- | --- | --- | --- |
| 7-Zip | `tools/7z.exe`、`7z.dll`、`7-zip.dll`、`7-zip32.dll` | LGPL-2.1 + unRAR restriction | [`licenses/7-Zip-license.txt`](licenses/7-Zip-license.txt)、[`LGPL-2.1.txt`](licenses/LGPL-2.1.txt) |
| 7-Zip（Android 侧） | `tools/recovery_bin/7zzs` | LGPL-2.1 + unRAR restriction | 同上 |
| aria2 | `tools/aria2c.exe` | GPL-2.0 | [`licenses/GPL-2.0.txt`](licenses/GPL-2.0.txt) |
| payload-dumper-go | `tools/payload-dumper-go.exe` | Apache-2.0 | [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt) |
| Android 分区工具（lpmake / lpdumps / lpunpack / img2simg / simg2img） | `tools/lpmake.exe` 等 | Apache-2.0 | 同上 |
| erofs-utils | `tools/mkfs.erofs.exe`、`extract.erofs.exe`、`tools/erofs-utils-cygwin/*` | GPL-2.0 | [`licenses/GPL-2.0.txt`](licenses/GPL-2.0.txt) |
| e2fsprogs | `tools/mke2fs.exe`、`e2fsdroid.exe` | GPL-2.0 / LGPL-2.1 | [`GPL-2.0.txt`](licenses/GPL-2.0.txt)、[`LGPL-2.1.txt`](licenses/LGPL-2.1.txt) |
| Zstandard | `tools/zstd.exe` | BSD-3-Clause | [`licenses/BSD-3-Clause.txt`](licenses/BSD-3-Clause.txt) |
| apktool | `tools/apktool.jar` | Apache-2.0 | [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt) |
| Java 运行时（JRE） | `tools/jre/**` | GPL-2.0 with Classpath Exception | [`licenses/GPL-2.0.txt`](licenses/GPL-2.0.txt) |
| 刷机脚本合集 | `tools/flashtools.zip` | 由第三方提供，按原样分发 | 以包内声明为准 |
| TWRP recovery 镜像 | `assets/root_images/recovery_twrp.img.zst` | TWRP 项目许可证（GPL-3.0 等） | [`licenses/GPL-3.0.txt`](licenses/GPL-3.0.txt) |
| ROOT 补丁镜像 | `assets/root_images/init_boot_*.img` | Magisk / KernelSU / SukiSU / KernelSU-Next / Kitsune Mask 各自许可证 | 见各自项目 |
| 源码压缩包内的上述文件 | 同左 | 同左 | 同左 |

> 卡刷包（`workspace/output/*.zip`）会把 `bin/Windows`、`bin/android` 里的
> 同批二进制一起打进镜像；打包脚本会把本文件与 `licenses/` 一并放入 zip 的
> `NOTICE/` 目录，保证接收方拿得到声明。

### GPL / LGPL 说明

* 上述 GPL/LGPL 组件均以**独立可执行文件**形式分发，与本项目代码无静态链接，
  不改变本项目自身的 MIT 许可；
* 未对二进制做任何修改（原样分发），源代码可从各组件官方站点获取；
* 如你需要对应的源码副本，可提出请求，本项目会提供官方下载地址。

---

## 4. 商标与关联声明

Xiaomi、HyperOS、MIUI、Android、Qualcomm、Magisk、KernelSU、SukiSU、
KernelSU-Next、Kitsune Mask、TWRP、7-Zip、apktool 等名称与标识归各自权利人所有。
本项目为非官方第三方工具，与上述任何公司或项目**无隶属、赞助或背书关系**，
名称仅用于说明兼容性。

---

## 5. 与 ROM 相关的版权

本项目不含任何 ROM 本体；下载与使用 MIUI/HyperOS 固件请遵守小米公司的用户协议，
ROM 版权归小米公司所有。刷机导致的设备损坏、数据丢失由使用者自行承担，详见
[README](README.md) 的免责声明。
