# ShennongPort

**小米 18 Pro Max（madrid）→ 小米 14 Pro（shennong）移植流水线：移植 → 精简 → 打包。**

把两个只管一段路的项目合并成一条能跑完的流水线：

| 上游 | 负责 | 在本项目中的位置 |
| --- | --- | --- |
| [NorthStarK-Lvy/XMAPort](https://github.com/NorthStarK-Lvy/XMAPort) | 下载 / 解包 / 分区迁移 / erofs + lpmake | `XMAPort.py`、`tools/make_hyper.py`、`tools/pack_partitions.py` |
| [XHR222/14PRO_SHALLOW_ROM](https://github.com/XHR222/14PRO_SHALLOW_ROM) | 14 Pro 精简清单 + 功能修补 + 打包成卡刷包 | `tools/slim.py`、`tools/shennong_patch.py`、`tools/package_zip.py` |

> 方向固定：**源 = 18 Pro Max（HyperOS 4 / Android 17）**，
> **目标 = 14 Pro 底包（HyperOS 3 / Android 16）**。
> 体积、super 布局、版本跨度与刷写注意事项见
> [docs/PORT_18PROMAX_TO_14PRO.md](docs/PORT_18PROMAX_TO_14PRO.md)。

```
┌──────────────┐   ┌───────────────────────────┐   ┌──────────────────────┐
│  移植 port    │ → │  精简 slim                 │ → │  打包 pack            │
│  Step 1-5     │   │  Step 6                    │   │  Step 7-8            │
│  · 双包下载    │   │  · 5 组应用清单（make.sh）  │   │  · erofs 重打包       │
│  · payload 解包│   │  · 相机/overlay/特性替换   │   │  · lpmake super.img  │
│  · make_hyper │   │  · build.prop/密度/aptX    │   │  · auto-fit 预算收敛  │
│  · 迁移/补丁   │   │  · fstab/TWRP/init 修补    │   │  · zstd + 7z 卡刷包  │
└──────────────┘   └───────────────────────────┘   └──────────────────────┘
```

---

## 1. 快速开始（Windows 10/11）

```bat
:: 0) 环境：Python 3.8+（建议 3.12），约 40 GB 磁盘
cd /d <本项目目录>

:: 1) 自检：工具链 / 模块 / 配置，应该全 [OK]
python XMAPort.py --selftest

:: 2) 拉取 14 Pro 专属资源（约 310 MiB，只需一次）
python tools\assets.py fetch

:: 3) 检查目标配置
notepad config.ini        :: device_platform / device_size / 两个 ROM 直链

:: 4) 全流程：移植 → 精简 → 打包
python XMAPort.py --auto --device shennong
```

产物：

```
workspace/packed/super.img                                   lpmake 生成的 sparse super
workspace/output/SHENNONG_ShalloW_<版本>_<md5前10位>_<安卓>.0.zip   可刷卡刷包
```

卡刷包结构（与 14PRO_SHALLOW_ROM 一致）：

```
super.zst                 ← zstd -12 压缩的 super.img
firmware-update/*.img     ← boot / dtbo / vbmeta / TWRP …
FlashWindows.bat          ← 线刷脚本（bin/Windows/fastboot）
META-INF/…                ← Recovery 卡刷入口
bin/…                     ← adb / fastboot / zstd / mke2fs
```

---

## 2. 三种跑法

### 2.1 交互菜单

```bat
python XMAPort.py
```

`[1]` 一键全流程；`[A]` 用 `workspace/packed` 里已有镜像单独合成 super.img；
`[C]` 开源致谢；`[D]` 清理 workspace。

### 2.2 命令行一键

```bat
python XMAPort.py --auto --device shennong ^
  --source "https://.../donor-full-ota.zip" ^
  --target "https://.../shennong-full-ota.zip"
```

URL 留空 = 复用上一次的工作区（不再下载、不再解包）。

### 2.3 断点续跑（三阶段独立）

```bat
python XMAPort.py --auto --device shennong --stage port   :: 只移植，产出两个文件系统
python XMAPort.py --auto --device shennong --stage slim   :: 只精简/修补
python XMAPort.py --auto --device shennong --stage pack   :: 只打包 + 出 zip
```

常用开关：

| 参数 | 作用 |
| --- | --- |
| `--stage all/port/slim/pack` | 阶段选择，默认 `all` |
| `--offline` | 不下载 `shennong_files`，缺资源的步骤自动跳过 |
| `--no-slim` | 跳过精简阶段，直接打包（对比/调试） |
| `--selftest` | 只自检，不动数据 |

---

## 3. 精简阶段做了什么

### 3.1 应用清单（`tools/slim.py`，逐字来自 make.sh）

| 分组 | 目录 | 数量 | 例 |
| --- | --- | --- | --- |
| `product_app` | `product/app` | 21 | AnalyticsCore、Updater、PaymentService、talkback |
| `product_data_app` | `product/data-app` | 26 | MiShop、MIUIYoupin、MIUIVideo、MIUIMusicT |
| `product_pangu_priv_app` | `product/pangu/system/priv-app` | 1 | SystemHelper |
| `product_priv_app` | `product/priv-app` | 6 | AutoRegistration、MIbrowser、RegService |
| `system_priv_app` | `system/priv-app` | 7 | BuiltInPrintService、MusicFX、Tag |

匹配规则：目录名**包含**关键词（大小写不敏感），目录整棵删除。
另有两道保险：

* `HARD_KEEP_TOKENS`：相机、桌面、SystemUI、Settings、overlay、bootanimation 等关键目录，
  应用清单永远不删（`system` 这种短关键词不会误伤 `Settings`）；
* `slim_keep=`：`config.ini` 里手工追加的分区相对 glob。

预算不够时再按顺序追加通用档位：
`media` → `audio` → `preinstall` → `apps` → `ai` → `theme` → `custom`
（`slim_tiers` / `auto_fit_tiers` 可调）。18 Pro Max 这种大包通常还需要
`ai`（AI 模型）甚至 `theme`（主题素材）才装得下 7.75 GiB，代价是对应功能/主题失效。

### 3.2 14 Pro 功能修补（`tools/shennong_patch.py`，来自 make.sh）

| 步骤 | 内容 | 来源资源 |
| --- | --- | --- |
| `overlay` | 替换 `product/overlay` | `overlay.zip` |
| `device_features` | 替换机型特性 XML | `device_features.zip` |
| `displayconfig` | 替换屏幕参数 | `displayconfig.zip` |
| `powerkeeper` | 修复精准电量 | `PowerKeeper.zip` |
| `miaon` | 修复注视感知 | `MiAONService.apk` |
| `camera` | 三卷合并 MiuiCamera + 相机标定 | `MiuiCamera.apk.1/2/3`、`CameraTools_beta.zip` |
| `msa` | 广告服务占位包 | `MSA.apk` |
| `bootanimation` | 替换开机动画 | `bootanimation.zip` |
| `build_props` | 版本号/日期/构建者/机型名统一 | — |
| `density` | 默认密度 560 | — |
| `aptx` | vendor 加 aptX Lossless | — |
| `recovery_stub` | 删除 `recovery-from-boot.p`、`install-recovery.sh` | — |
| `init_qcom` | 删除 `start qti-testscripts` | — |
| `fstab` | 替换 `vendor/etc/fstab.qcom` | `fstab.qcom` |
| `firmware` | 内置 TWRP 到 `firmware-update` | `recovery.zip` |
| `signature`（可选） | 移除 APK 签名校验（apktool） | — |
| `icons`（可选） | 完美图标重打包 | 联网 |
| `kernelsu`（可选） | init_boot 注入 KernelSU | 仅 Linux |

**vendor 会被重新打包**：14 Pro 的 vendor 要改 fstab/属性/init，所以 `repack_vendor=true`
时会先 `extract_img.py` 解包 `vendor.img`，修补后用 `pack_partitions.py` 重新生成。

### 3.3 资源下载

`tools/assets.py` 按清单从上游仓库拉取 `shennong_files/`，断点续传 + 大小校验，
缓存到 `assets/shennong_files/`。国内网络可换镜像：

```ini
[shennong]
asset_base=https://ghfast.top/https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/
```

或环境变量 `SHENNONG_ASSET_BASE`。仓库本身不携带这 310 MiB 二进制。

---

## 4. 打包阶段（针对 14 Pro 调过）

1. **预算收敛**：打包完 system/system_ext/product/odm/vendor… 后，用真实镜像字节数
   复查 `usable`；超出就按 `auto_fit_tiers=apps,audio,media,preinstall,ai,theme` 逐档精简，
   只重打受影响的分区，再复查（`auto_fit=true`）；
2. 用 `lpmake` 按 **14 Pro 验证过的 split_ab 布局**合成 super：
   `system_a` 带镜像 / `system_b` 为 0、`qti_dynamic_partitions_a/_b`、
   `--virtual-ab -F`、`device_size=8321499136`（7.75 GiB）、`sparse=false`（raw，
   与 `FlashWindows.bat`、TWRP `update-binary` 兼容）；
3. `zstd -12` 压缩成 `super.zst`（没有 zstd 时退回 Python 3.14 自带 `compression.zstd`）；
4. 收集 `firmware-update`（boot/dtbo/vbmeta… + TWRP）；
5. 展开 `tools/flashtools.zip`（fastboot / adb / 刷机脚本 / META-INF）；
6. 固定时间戳后用 7-Zip 打 zip，按 `SHENNONG_ShalloW_<版本>_<md5>_<安卓>.0.zip` 命名。

预算 = `min(config.device_size, 底包实测 super_partition_size, shennong 档案上限)`
− `metadata×slots` − `margin_mib`。仍装不下时，原版 XMAPort 的
`make_hyper.py extreme` 兜底保留，但正常路径应该由 auto-fit 提前收敛。

> 想改回 XMAPort 的单 group 布局：`super_style=single`；
> 想让 super.img 变小：`sparse=true`（但 TWRP 脚本可能只认 raw）。

---

## 5. 目录结构

```
shennong_port/
├─ XMAPort.py                 入口：Step 1-8 编排 + CLI + 自检
├─ config.ini                 合并配置（移植/精简/打包三段）
├─ tools/
│  ├─ make_hyper.py           移植核心（上游）
│  ├─ pack_partitions.py      erofs/ext4 打包（上游）
│  ├─ extract_img.py          镜像解包（上游）
│  ├─ slim.py                 14 Pro 应用清单 + 通用档位
│  ├─ shennong_patch.py       make.sh 的功能修补移植
│  ├─ assets.py               shennong_files 下载/校验
│  ├─ stage_common.py         路径/配置/体积公共设施
│  ├─ device_profiles.py      shennong / madrid 档案（预算上限）
│  ├─ package_zip.py          super.zst + 卡刷包
│  ├─ apktool.jar / jre/      services.jar 签名补丁用
│  ├─ 7z / aria2c / lpmake / mkfs.erofs / zstd …
│  └─ flashtools.zip          卡刷包里的刷机脚本
├─ tests/
│  ├─ test_stages.py          无 ROM 回归测试（合成数据）
│  └─ make_fixture.py         生成合成工作区，便于手动跑 slim/pack
├─ docs/
│  ├─ PORT_18PROMAX_TO_14PRO.md  18 Pro Max → 14 Pro 专项说明（预算/版本/刷写）
│  ├─ ARCHITECTURE.md         流水线设计 / 数据流 / 分区来源
│  ├─ USAGE.md                详细用法 + 排错
│  ├─ MIGRATION.md            make.sh 每一段 → Python 的对照表
│  └─ LIMITS.md               没移植过来的部分与原因
└─ .github/workflows/build.yml  Windows CI：自检 → 拉资源 → 三阶段 → 发布
```

---

## 6. 与上游的差异 / 已知限制

* **没有搬运的部分**：`vendor_boot` 里 `first_stage_ramdisk/fstab.qcom` 的替换
  （依赖 Linux 版 magiskboot + cpio）、KernelSU 注入（ksud 仅 Linux）、
  S3 上传（私有仓库密钥）。`tools/shennong_patch.py` 会明确 `skip`，不会假装成功。
* **签名校验移除**是可选步骤（`enable_signature=true`），走 apktool + 内置 JRE；
  失败只记为 `fail`，不中断打包。
* **完美图标**是可选步骤（`enable_icons=true`），需要联网拉 Perfect-Icons 项目。
* **版本跨度**：18 Pro Max 是 Android 17，14 Pro 底包是 Android 16。`sync_apex`
  会把底包 VNDK 同步进移植包，但框架/HAL 差得太远时仍可能卡开机；首选更早的
  madrid OS4 包或更新的 shennong 底包，详见
  [docs/PORT_18PROMAX_TO_14PRO.md](docs/PORT_18PROMAX_TO_14PRO.md)。
* **磁盘**：18 Pro Max + 14 Pro 两套包解压后非常占空间。流水线默认
  `cleanup_intermediate=true`（解压完就删 OTA/ROM）和 `keep_super_img=false`
  （zip 完成后删 7.75 GiB raw super）。仍不够时按提示删 `workspace/download_*`、
  `workspace/source_rom`、`workspace/target_rom`。
* **目标代号校验**：`strict_target=true` 会在下载前检查 target URL 的代号是否为
  `shennong`，避免拿错底包（比如把 18 Pro Max 当底包，vendor/odm 会大得离谱）。
* **未在真机验证**：本仓库只做了静态审查、语法自检、合成数据端到端测试和工具链实跑；
  没有真机、没有真实 ROM 直链下载。刷机风险自负。

---

## 7. 测试

```bat
python tests\test_stages.py        :: 单元回归（合成数据 + 假资源）
python tests\make_fixture.py       :: 生成合成工作区
python XMAPort.py --auto --stage slim --device shennong --offline
python XMAPort.py --auto --stage pack --device shennong
```

`test_stages.py` 覆盖 5 组删除清单、保护名单、9 个资源替换步骤、build.prop 统一
和 vendor 侧修补；`make_fixture.py` 用来手动验证「精简 → 打包 → 出 zip」全链路，
包括 split_ab 的 lpmake 参数与 auto-fit 重打包。

CI（`.github/workflows/build.yml`）在 Windows runner 上会先跑 `--selftest`，
再按 `stage` 拉资源并执行全流程，最后分卷上传 Release。

---

## 8. 免责声明

* 仅供个人学习与测试；ROM 版权归小米公司所有，请于下载后 24 小时内删除。
* 刷机有变砖与数据丢失风险：`device_platform` 填错、`device_size` 大于实机 super、
  底包与移植包大版本跨度过大，都可能无法开机。后果自负。
* 禁止商用 / 售卖盈利。

## 9. 致谢与许可

* [XMAPort](https://github.com/NorthStarK-Lvy/XMAPort)（MIT）：移植引擎、打包器、工具链。
* [14PRO_SHALLOW_ROM](https://github.com/XHR222/14PRO_SHALLOW_ROM)：14 Pro 精简清单、修补资源与刷机脚本。
* 感谢余空、木槿香、PJQ 教程，以及 HyperOS 移植社区。
* 主代码 MIT（见 `LICENSE`）；捆绑的第三方工具（7-Zip / aria2 / payload-dumper-go /
  erofs-utils / lpmake / zstd / apktool / JRE / flashtools）遵循各自原始许可。
