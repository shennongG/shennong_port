# ShennongPort

[![star](https://gitee.com/h-shennong/shennong-port/badge/star.svg?theme=dark)](https://gitee.com/h-shennong/shennong-port/stargazers)
[![fork](https://gitee.com/h-shennong/shennong-port/badge/fork.svg?theme=dark)](https://gitee.com/h-shennong/shennong-port/members)
![](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4)
![](https://img.shields.io/badge/python-3.8%2B-3776ab)

**小米 18 Pro Max（`madrid`）→ 小米 14 Pro（`shennong`）移植流水线：移植 → 精简 → 打包。**

一条命令把「双包下载 / 解包 / 分区迁移 / 精简 / 功能修补 / super 合成 / 卡刷包」
串起来，产物是能直接进 TWRP 的 zip。仓库只放代码与工具链，ROM 与专属资源不入库。

```
┌──────────────┐   ┌───────────────────────────┐   ┌──────────────────────┐
│  移植 port    │ → │  精简 slim                 │ → │  打包 pack            │
│  Step 1-5     │   │  Step 6                    │   │  Step 7-8            │
│  · 双包下载    │   │  · 5 组应用清单            │   │  · erofs 重打包       │
│  · payload 解包│   │  · 相机/overlay/特性替换   │   │  · lpmake super.img  │
│  · 分区迁移    │   │  · build.prop/密度/aptX    │   │  · auto-fit 预算收敛  │
│  · 版本对齐    │   │  · fstab/TWRP/init 修补    │   │  · zstd + 7z 卡刷包  │
└──────────────┘   └───────────────────────────┘   └──────────────────────┘
```

| 阶段 | 输入 | 产出 |
| --- | --- | --- |
| port | 源包（18 Pro Max OTA）、底包（14 Pro OTA） | `workspace/source_filesystem`、`target_filesystem` |
| slim | 上一步的文件系统 | 精简 + 修补后的 system / system_ext / product / vendor |
| pack | 精简结果 + 固件镜像 | `workspace/packed/super.img`、`workspace/output/*.zip` |

> 方向固定：**源 = 18 Pro Max（HyperOS 4 / Android 17）**，
> **目标 = 14 Pro 底包（HyperOS 3 / Android 16）**。体积、super 布局、
> 版本跨度与刷写注意事项见 [docs/PORT_18PROMAX_TO_14PRO.md](docs/PORT_18PROMAX_TO_14PRO.md)。

---

## 1. 快速开始（Windows 10/11）

```bat
:: 0) 环境：Python 3.8+（建议 3.12），约 40 GB 磁盘
git clone https://gitee.com/h-shennong/shennong-port.git
cd shennong-port

:: 1) 自检：工具链 / 模块 / 配置 / 资源镜像链，应该全 [OK]
python shennong_port.py --selftest

:: 2) 拉取 14 Pro 专属资源（约 310 MiB，只需一次；自动挑可用镜像）
python tools\assets.py fetch

:: 3) 检查目标配置
notepad config.ini        :: device_platform / device_size / 两个 ROM 直链

:: 4) 全流程：移植 → 精简 → 打包
python shennong_port.py --auto --device shennong
```

> 国内网络先看一眼镜像链，哪条通心里有数：
>
> ```bat
> python tools\assets.py mirrors --probe
> ```
>
> 默认顺序 = **Gitee 镜像 → 公益加速前缀 → 直连**，前一条失败自动换下一条；
> 也可以只钉一条，见 [§3.3](#33-资源下载镜像链)。

> Step 3 默认只解源包的 `system,system_ext,product`（省几 GB、也快很多），
> 目标包解全量（固件镜像要进卡刷包）；payload 超时 60 分钟、并发 8，
> 都可在 `config.ini [settings]` 调整。

产物：

```
workspace/packed/super.img                                lpmake 生成的 raw super（7.75 GiB）
workspace/output/ShennongPort_Mi14Pro_<版本>_<donor>_<md5>_<安卓>.zip   可刷卡刷包
```

卡刷包结构：

```
images/super.img.zst      ← zstd 压缩的 super.img（TWRP 直接 pipe 刷入）
images/boot.img           ← 底包 boot
images/init_boot_*.img    ← NoROOT / Magisk / KernelSU / SukiSU / KernelSU-Next / Kitsune Mask
images/recovery_twrp.img  ← TWRP
images/*.img              ← vbmeta / 基带等固件
META-INF/…/update-binary  ← 现生成的 TWRP 刷机脚本（机型/MD5/ROOT 音量键选择）
Flash-Windows.bat         ← 现生成的 Windows 线刷脚本（ROOT 菜单 + TWRP 询问）
刷机说明.txt              ← 中文刷机说明（线刷/卡刷/校验）
NOTICE/                   ← NOTICE.md + licenses/（第三方声明与许可证正文）
bin/android/{7zzs,zstd}   ← Recovery 里解压 super 用
bin/Windows/*             ← fastboot / adb / zstd
```

---

## 2. 三种跑法

### 2.1 交互菜单

```bat
python shennong_port.py
```

`[1]` 一键全流程；`[A]` 用 `workspace/packed` 里已有镜像单独合成 super.img；
`[C]` 许可证与第三方声明；`[D]` 清理 workspace。

### 2.2 命令行一键

```bat
python shennong_port.py --auto --device shennong ^
  --source "https://.../donor-full-ota.zip" ^
  --target "https://.../shennong-full-ota.zip"
```

URL 留空 = 复用上一次的工作区（不再下载、不再解包）。

### 2.3 断点续跑（三阶段独立）

```bat
python shennong_port.py --auto --device shennong --stage port   :: 只移植，产出两个文件系统
python shennong_port.py --auto --device shennong --stage slim   :: 只精简/修补
python shennong_port.py --auto --device shennong --stage pack   :: 只打包 + 出 zip
```

常用开关：

| 参数 | 作用 |
| --- | --- |
| `--stage all/port/slim/pack` | 阶段选择，默认 `all` |
| `--offline` | 不下载 `shennong_files`，缺资源的步骤自动跳过 |
| `--no-slim` | 跳过精简阶段，直接打包（对比/调试） |
| `--selftest` | 只自检，不动数据 |

---

## 3. 精简与修补

### 3.1 应用清单（`tools/slim.py`）

| 分组 | 目录 | 数量 | 例 |
| --- | --- | --- | --- |
| `product_app` | `product/app` | 21 | AnalyticsCore、Updater、PaymentService、talkback |
| `product_data_app` | `product/data-app` | 26 | MiShop、MIUIYoupin、MIUIVideo、MIUIMusicT |
| `product_pangu_priv_app` | `product/pangu/system/priv-app` | 1 | SystemHelper |
| `product_priv_app` | `product/priv-app` | 6 | AutoRegistration、MIbrowser、RegService |
| `system_priv_app` | `system/priv-app` | 7 | BuiltInPrintService、MusicFX、Tag |

匹配规则：目录名**包含**关键词（大小写不敏感），目录整棵删除。另有两道保险：

* `HARD_KEEP_TOKENS`：相机、桌面、SystemUI、Settings、overlay、bootanimation 等关键目录，
  应用清单永远不删（`system` 这种短关键词不会误伤 `Settings`）；
* `slim_keep=`：`config.ini` 里手工追加的分区相对 glob。

预算不够时再按顺序追加通用档位：
`media` → `audio` → `preinstall` → `apps` → `ai` → `theme` → `custom`
（`slim_tiers` / `auto_fit_tiers` 可调）。18 Pro Max 这种大包通常还需要
`ai`（AI 模型）甚至 `theme`（主题素材）才装得下 7.75 GiB，代价是对应功能/主题失效。

### 3.2 14 Pro 功能修补（`tools/shennong_patch.py`）

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
| `init_qcom` | 删除 `init.qcom.rc` 里的 `qti-testscripts` | — |
| `fstab` | 替换 `vendor/etc/fstab.qcom` | `fstab.qcom` |
| `firmware` | 内置 TWRP 到 `firmware-update` | `recovery.zip` |
| `signature`（可选） | 移除 APK 签名校验（apktool） | — |
| `icons`（可选） | 图标包重打包 | 联网（同样走镜像链） |
| `kernelsu`（可选） | init_boot 注入 KernelSU | 仅 Linux |

**vendor 会被重新打包**：14 Pro 的 vendor 要改 fstab / 属性 / init，所以
`repack_vendor=true` 时会先解包 `vendor.img`，修补后再重新生成。

### 3.3 资源下载（镜像链）

`tools/assets.py` 按清单拉取 `shennong_files/`，断点续传 + 大小校验，
缓存到 `assets/shennong_files/`。下载源是一条可配置的镜像链，逐个回落：

```
1. https://gitee.com/h-shennong/rom-assets/raw/main/shennong_files/     ← 自建镜像
2. https://ghfast.top/<源地址>                                           ← 公益加速
3. https://gh-proxy.com/<源地址>
4. https://ghproxy.net/<源地址>
5. <源地址>                                                              ← 直连兜底
```

查看 / 探测：

```bat
python tools\assets.py mirrors            :: 只打印顺序
python tools\assets.py mirrors --probe    :: 逐个探测可用性
```

钉死一条：

```ini
[shennong]
asset_base=https://gitee.com/h-shennong/rom-assets/raw/main/shennong_files/
;; 或者只加几个前缀到链首，仍保留回落
asset_mirrors=https://ghfast.top/,https://gh-proxy.com/
```

也支持环境变量 `SHENNONG_ASSET_BASE` / `SHENNONG_ASSET_MIRRORS`，CI 里更好用。
**自建镜像**：Gitee → 新建仓库 → 「导入已有仓库」→ 填资源仓库地址 → 仓库名
`rom-assets`，之后链首这条就通了（实测最快、不受代理限速）。
资源来源、版权与许可证说明见 [NOTICE.md](NOTICE.md) 第 2 节。

---

## 4. 打包

1. **预算收敛**：打包完 system/system_ext/product/odm/vendor… 后，用真实镜像字节数
   复查 `usable`；超出就按 `auto_fit_tiers=apps,audio,media,preinstall,ai,theme` 逐档精简，
   只重打受影响的分区，再复查（`auto_fit=true`）；
2. 用 `lpmake` 按 14 Pro 实机验证过的布局合成 super：只有 `<part>_a`、
   单 group `qti_dynamic_partitions_a`、`--virtual-ab -F`、
   `device_size=8321499136`（7.75 GiB）、`sparse=false`（raw）；
3. `zstd -12` 压缩成 `images/super.img.zst`（没有 zstd 时退回 Python 3.14 自带
   `compression.zstd`），压缩完默认删掉 raw super；
4. 把 14 Pro 固件镜像（boot / init_boot / vbmeta / modem / TWRP…）复制到 `images/`；
5. 展开 `tools/flashtools.zip` 提供 `bin/android`、`bin/Windows`；
6. 现生成 `META-INF/.../update-binary`（TWRP）和 `Flash-Windows.bat`（fastboot），
   固定时间戳后打 zip，命名 `ShennongPort_Mi14Pro_<版本>_<donor>_<md5>_<安卓>.zip`；
7. 把 `NOTICE.md` 与 `licenses/` 放进 zip 的 `NOTICE/`，保证接收方拿到声明。

> 该命名让 update-binary 能取文件名第 5 段做 MD5 校验；固件按 14 Pro 的分区名
> 刷到 `_a/_b` 两个槽，和参考成品包一致。

> **vbmeta 必须禁验**：`patch_vbmeta` 会把 `vbmeta*.img` 的 AVB flags 改成
> `0x3`（dm-verity + AVB 都关），线刷脚本另外带
> `--disable-verity --disable-verification`，并在最后 `set_active a` + `reboot`。
> 旧包如果卡第一屏，先用这一版重打包再刷。

### Recovery 与 ROOT 补丁

仓库里带了一套 14 Pro 可用的补丁（`assets/root_images/`）：

```
init_boot_official.img        NoROOT
init_boot_magisk.img          Magisk
init_boot_ksu.img             KernelSU
init_boot_sukisu.img          SukiSU-Ultra
init_boot_ksu-next.img        KernelSU-Next
init_boot_kitsune-mask.img    Kitsune Mask
recovery_twrp.img.zst         TWRP（压缩存放，打包时解压为 recovery_twrp.img）
```

打包时会全部放进 `images/`。线刷 `Flash-Windows.bat` 有 1-6 的 ROOT 菜单；
卡刷 `update-binary` 用音量键 `[-]` 切换、`[+]` 确认。两者都会先刷官方
`boot.img`，再按选择刷对应的 `init_boot_*.img`，最后询问/选择是否刷 TWRP。

换自己的 recovery / ROOT 补丁：

```ini
[packing]
; 第三方 recovery；.img 或 .img.zst 都行（留空则用 shennong_files/recovery.zip）
recovery_img=assets/root_images/recovery_twrp.img.zst
; ROOT 补丁目录（init_boot_*.img 按固定文件名读取）
root_images=assets/root_images
; 不想刷 recovery 就设 false
flash_recovery=true
```

然后重跑 `--stage pack`。验证：

```bat
7z l workspace\output\ShennongPort_Mi14Pro_*.zip | findstr init_boot
7z l workspace\output\ShennongPort_Mi14Pro_*.zip | findstr recovery_twrp
```

注意：recovery / init_boot 必须与 14 Pro 的底包内核匹配，大小不能超过对应分区；
刷错 recovery 不影响 fastboot，可随时重刷。

预算 = `min(config.device_size, 底包实测 super_partition_size, shennong 档案上限)`
− `metadata×slots` − `margin_mib`。仍装不下时还有 `make_hyper.py extreme` 兜底，
但正常路径应该由 auto-fit 提前收敛。

> 想改成单 group 布局：`super_style=single`；
> 想让 super.img 变小：`sparse=true`（但 TWRP 脚本可能只认 raw）。

---

## 5. 在 Gitee 上跑（CI / 发布）

| 场景 | 入口 | 说明 |
| --- | --- | --- |
| 建仓 + 推送 | `ci/push_to_gitee.ps1` | API 建仓 → 配远端 → 推送 → 校验，只需 `GITEE_TOKEN` |
| 本地 / 自建 Windows runner | `ci/run_pipeline.ps1` | 自检 → 拉资源 → 三阶段 → 分卷 → 可选发布 |
| Gitee Go（Linux runner） | `ci/gitee-go.yml` | 语法编译 + `--selftest` + 离线单测 + 源码包 |
| 发布产物到 Release | `tools/gitee_release.py` | 替代手工建 Release，只依赖 `GITEE_TOKEN` |
| 仓库对象管理 | `tools/gitee_repo.py` | `info / create / ensure` |

```powershell
# 0) 建仓 + 推送（令牌勾 projects 权限即可）
$env:GITEE_TOKEN = "你的 Gitee 私人令牌"
powershell -File ci\push_to_gitee.ps1 -UseClipboard

# 1) 全流程
powershell -File ci\run_pipeline.ps1 -Stage all

# 2) 已有工作区，只打包 + 发布
powershell -File ci\run_pipeline.ps1 -Stage pack -Publish -Tag sh-20261110-1530
```

> 脚本存成 UTF-8 with BOM，Windows 自带的 PowerShell 5.1 与 PowerShell 7 都能跑。

---

## 6. 目录结构

```
shennong-port/
├─ shennong_port.py           入口：Step 1-8 编排 + CLI + 自检
├─ config.ini                 合并配置（移植/精简/打包三段 + 资源镜像）
├─ NOTICE.md                  第三方组件、许可证、商标与免责声明（唯一声明入口）
├─ licenses/                  随包组件的许可证正文
├─ tools/
│  ├─ make_hyper.py           移植核心（分区迁移 / super 合成）
│  ├─ pack_partitions.py      erofs/ext4 打包
│  ├─ extract_img.py          镜像解包
│  ├─ slim.py                 14 Pro 应用清单 + 通用档位
│  ├─ shennong_patch.py       功能修补
│  ├─ assets.py               资源下载 / 校验 / 镜像链
│  ├─ gitee_release.py        Gitee Release 发布
│  ├─ gitee_repo.py           Gitee 建仓 / 查仓
│  ├─ stage_common.py         路径/配置/体积公共设施
│  ├─ device_profiles.py      shennong / madrid 档案（预算上限）
│  ├─ package_zip.py          super.zst + 卡刷包
│  ├─ apktool.jar / jre/      签名补丁用的工具链
│  ├─ recovery_bin/7zzs       Recovery 侧解压器
│  └─ flashtools.zip          卡刷包里的刷机脚本
├─ ci/
│  ├─ push_to_gitee.ps1       建仓 + 推送
│  ├─ run_pipeline.ps1        Windows 全流程脚本
│  └─ gitee-go.yml            Gitee Go 流水线模板
├─ tests/
│  ├─ test_stages.py          无 ROM 回归测试（合成数据）
│  ├─ test_payload_args.py    payload 参数测试
│  └─ make_fixture.py         生成合成工作区
└─ docs/
   ├─ PORT_18PROMAX_TO_14PRO.md  机型适配说明（预算/版本/刷写）
   ├─ ARCHITECTURE.md         流水线设计 / 数据流
   ├─ USAGE.md                详细用法 + 排错
   ├─ STEPS.md                实现步骤与行为规格对照
   ├─ LIMITS.md               未覆盖项与原因
   └─ GITEE.md                Gitee 部署、CI 与发布
```

---

## 7. 已知限制

* **vendor_boot 的 `first_stage_ramdisk/fstab.qcom`** 未替换：需要 Linux 版
  `magiskboot` + cpio，Windows 不可用；`tools/shennong_patch.py` 会明确 `skip`。
* **KernelSU 注入**（ksud）同样只支持 Linux，Windows 下 `skip`，不会假装成功。
* **签名校验移除**是可选步骤（`enable_signature=true`），走 apktool + 内置 JRE；
  失败只记为 `fail`，不中断打包。
* **图标包**是可选步骤（`enable_icons=true`），需要联网下载（走镜像链）。
* **版本跨度**：Android 17 → 16，`sync_apex` 会把底包 VNDK 同步进移植包，
  但框架/HAL 差得太远时仍可能卡开机；首选更早的源包或更新的底包，详见
  [docs/PORT_18PROMAX_TO_14PRO.md](docs/PORT_18PROMAX_TO_14PRO.md)。
* **磁盘**：两套包解压后非常占空间。默认 `cleanup_intermediate=true`、
  `keep_super_img=false`；仍不够时按提示删 `workspace/download_*`、
  `workspace/source_rom`、`workspace/target_rom`。
* **目标代号校验**：`strict_target=true` 会在下载前检查 target URL 的代号是否为
  `shennong`，避免拿错底包。
* **未在真机验证**：本仓库只做了静态审查、语法自检、合成数据端到端测试和工具链实跑；
  刷机风险自负。

---

## 8. 测试

```bat
python tests\test_stages.py        :: 精简/修补单元回归（合成数据 + 假资源）
python tests\test_payload_args.py  :: payload 分区过滤/并发/超时 参数测试
python tests\make_fixture.py       :: 生成合成工作区
python shennong_port.py --auto --stage slim --device shennong --offline
python shennong_port.py --auto --stage pack --device shennong
```

`test_stages.py` 覆盖 5 组删除清单、保护名单、资源替换步骤、build.prop 统一和
vendor 侧修补；`make_fixture.py` 用来手动验证「精简 → 打包 → 出 zip」全链路，
包括 split_ab 的 lpmake 参数与 auto-fit 重打包。

---

## 9. 免责声明 (Disclaimer)

* 版权与使用限制：本项目仅供个人学习与测试使用。ROM 版权归小米公司所有，请于下载后 24 小时内删除。
* 刷机风险警告：刷机有风险，操作需谨慎。以下操作均可能导致设备变砖、数据丢失或无法开机，
  请自行承担全部后果：`device_platform` 填错、`device_size` 大于实机容量、
  super 分区配置异常、底包与移植包版本跨度过大。
* 测试状态：该项目尚未经过实机测试。
* 严禁商用：本项目严禁用于任何商业用途或售卖盈利。
* 如有侵权，联系本人删除。

---

## 10. 许可证与第三方声明

* 本项目自身代码：MIT，见 [LICENSE](LICENSE)。
* 随包分发的第三方可执行文件、运行期下载的资源、商标与合规说明：
  统一见 [NOTICE.md](NOTICE.md)，许可证正文见 [licenses/](licenses/)。
* 分发卡刷包时，`NOTICE.md` 与 `licenses/` 会随 zip 的 `NOTICE/` 目录一并提供。
