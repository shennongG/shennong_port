# XMAPort-SHALLOW

[![star](https://gitee.com/h-shennong/XMAPort-SHALLOW/badge/star.svg?theme=dark)](https://gitee.com/h-shennong/XMAPort-SHALLOW/stargazers)
[![fork](https://gitee.com/h-shennong/XMAPort-SHALLOW/badge/fork.svg?theme=dark)](https://gitee.com/h-shennong/XMAPort-SHALLOW/members)
![](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4)
![](https://img.shields.io/badge/python-3.8%2B-3776ab)

**小米 18 Pro Max（madrid）→ 小米 14 Pro（shennong）移植流水线：移植 → 精简 → 打包。**

> 本仓库托管在 **Gitee**（`https://gitee.com/h-shennong/XMAPort-SHALLOW`），
> 由 GitHub 上的 `long969697262/shennong_port`（现名 `XMAPort-SHALLOW`）迁移而来，
> 迁移改动与原因见 [docs/GITEE.md](docs/GITEE.md)。

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
git clone https://gitee.com/h-shennong/XMAPort-SHALLOW.git
cd XMAPort-SHALLOW

:: 1) 自检：工具链 / 模块 / 配置 / 资源镜像链，应该全 [OK]
python XMAPort.py --selftest

:: 2) 拉取 14 Pro 专属资源（约 310 MiB，只需一次；自动挑可用镜像）
python tools\assets.py fetch

:: 3) 检查目标配置
notepad config.ini        :: device_platform / device_size / 两个 ROM 直链

:: 4) 全流程：移植 → 精简 → 打包
python XMAPort.py --auto --device shennong
```

> 国内网络先看一眼镜像链，哪条通心里有数：
>
> ```bat
> python tools\assets.py mirrors --probe
> ```
>
> 默认顺序 = **Gitee 镜像 → ghfast.top → gh-proxy.com → ghproxy.net → GitHub raw**，
> 前一条失败自动换下一条；也可以只钉一条，见 [§3.3](#33-资源下载gitee-镜像链)。

> Step 3 默认只解源包的 `system,system_ext,product`（省几 GB、也快很多），
> 目标包解全量（固件镜像要进卡刷包）；payload 超时 60 分钟、并发 8，
> 都可在 `config.ini [settings]` 调整。

产物：

```
workspace/packed/super.img                                    lpmake 生成的 raw super（7.75 GiB）
workspace/output/ShennongPort_Mi14Pro_<版本>_<donor>_<md5>_<安卓>.zip   可刷卡刷包
```

卡刷包结构（对齐参考 14 Pro 成品包）：

```
images/super.img.zst      ← zstd 压缩的 super.img（TWRP 直接 pipe 刷入）
images/boot.img           ← 底包 boot
images/init_boot_*.img    ← NoROOT / Magisk / KernelSU / SukiSU / KernelSU-Next / Kitsune Mask
images/recovery_twrp.img  ← TWRP
images/*.img              ← vbmeta / 基带等固件
META-INF/…/update-binary  ← 现生成的 TWRP 刷机脚本（机型/MD5/ROOT 音量键选择）
Flash-Windows.bat         ← 现生成的 Windows 线刷脚本（ROOT 菜单 + TWRP 询问）
刷机说明.txt              ← 中文刷机说明（线刷/卡刷/校验）
bin/android/{7zzs,zstd}   ← Recovery 里解压 super 用
bin/Windows/*             ← fastboot / adb / zstd
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
| `icons`（可选） | 完美图标重打包 | 联网（同样走镜像链） |
| `kernelsu`（可选） | init_boot 注入 KernelSU | 仅 Linux |

**vendor 会被重新打包**：14 Pro 的 vendor 要改 fstab/属性/init，所以 `repack_vendor=true`
时会先 `extract_img.py` 解包 `vendor.img`，修补后用 `pack_partitions.py` 重新生成。

### 3.3 资源下载（Gitee 镜像链）

`tools/assets.py` 按清单从上游仓库拉取 `shennong_files/`，断点续传 + 大小校验，
缓存到 `assets/shennong_files/`。**不再是单点 GitHub raw**，而是按顺序尝试一条镜像链：

```
1. https://gitee.com/h-shennong/14PRO_SHALLOW_ROM/raw/main/shennong_files/   ← Gitee 镜像
2. https://ghfast.top/https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/
3. https://gh-proxy.com/https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/
4. https://ghproxy.net/https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/
5. https://raw.githubusercontent.com/XHR222/14PRO_SHALLOW_ROM/main/shennong_files/
```

查看 / 探测：

```bat
python tools\assets.py mirrors            :: 只打印顺序
python tools\assets.py mirrors --probe    :: 逐个探测可用性
```

想钉死一条（比如国内只用 Gitee 镜像，其它全关）：

```ini
[shennong]
asset_base=https://gitee.com/h-shennong/14PRO_SHALLOW_ROM/raw/main/shennong_files/
;; 或者只加几个前缀到链首，仍保留回落
asset_mirrors=https://ghfast.top/,https://gh-proxy.com/
```

也支持环境变量 `SHENNONG_ASSET_BASE` / `SHENNONG_ASSET_MIRRORS`，CI 里更好用。
**Gitee 镜像仓库怎么来**：Gitee → 新建仓库 → 「导入已有仓库」→ 填
`https://github.com/XHR222/14PRO_SHALLOW_ROM` → 创建，之后第 1 条就通了（实测最快、
不受代理限速）。仓库本身不携带这 310 MiB 二进制。

---

## 4. 打包阶段（针对 14 Pro 调过）

1. **预算收敛**：打包完 system/system_ext/product/odm/vendor… 后，用真实镜像字节数
   复查 `usable`；超出就按 `auto_fit_tiers=apps,audio,media,preinstall,ai,theme` 逐档精简，
   只重打受影响的分区，再复查（`auto_fit=true`）；
2. 用 `lpmake` 按 **参考 14 Pro 成品包 在 shennong 上验证过的布局**合成 super：
   只有 `<part>_a`、单 group `qti_dynamic_partitions_a`、`--virtual-ab -F`、
   `device_size=8321499136`（7.75 GiB）、`sparse=false`（raw）；
3. `zstd -12` 压缩成 `images/super.img.zst`（没有 zstd 时退回 Python 3.14 自带
   `compression.zstd`），压缩完默认删掉 raw super；
4. 把 14 Pro 固件镜像（boot / init_boot / vbmeta / modem / TWRP…）复制到 `images/`；
5. 展开 `tools/flashtools.zip` 提供 `bin/android`、`bin/Windows`；
6. 现生成 `META-INF/.../update-binary`（TWRP）和 `Flash-Windows.bat`（fastboot），
   固定时间戳后打 zip，命名 `ShennongPort_Mi14Pro_<版本>_<donor>_<md5>_<安卓>.zip`。

> 该命名让 update-binary 能取文件名第 5 段做 MD5 校验；固件按 14 Pro 的分区名
> 刷到 `_a/_b` 两个槽，和参考包一致。

> **vbmeta 必须禁验**：`patch_vbmeta` 会把 `vbmeta*.img` 的 AVB flags 改成
> `0x3`（dm-verity + AVB 都关），线刷脚本另外带
> `--disable-verity --disable-verification`，并在最后 `set_active a` + `reboot`。
> 旧包如果卡第一屏，先用这一版重打包再刷。

### Recovery 与 ROOT 补丁

仓库里已经带好一套 14 Pro 可用的补丁（`assets/root_images/`）：

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
− `metadata×slots` − `margin_mib`。仍装不下时，原版 XMAPort 的
`make_hyper.py extreme` 兜底保留，但正常路径应该由 auto-fit 提前收敛。

> 想改回 XMAPort 的单 group 布局：`super_style=single`；
> 想让 super.img 变小：`sparse=true`（但 TWRP 脚本可能只认 raw）。

---

## 5. 在 Gitee 上跑（CI / 发布）

Gitee 不认 `.github/workflows/`，所以流水线做成了两条腿，**同一套命令**：

| 场景 | 入口 | 说明 |
| --- | --- | --- |
| 迁移到 Gitee（建仓+推送） | `ci/push_to_gitee.ps1` | 一条命令：API 建仓 → 配远端 → 推送 → 校验，只需 `GITEE_TOKEN` |
| 本地 / 自建 Windows runner | `ci/run_pipeline.ps1` | 一条命令跑完：自检 → 拉资源 → 移植/精简/打包 → 分卷 → 可选发布 |
| Gitee Go（Linux runner） | `ci/gitee-go.yml` | 轻量校验：语法编译 + `--selftest` + 离线单测 + 源码包；ROM 全流程跑不动（无 Windows / 无 40 GB 盘） |
| 发布产物到 Release | `tools/gitee_release.py` | 替代 `gh release create`，只依赖 `GITEE_TOKEN` |
| 仓库对象管理 | `tools/gitee_repo.py` | `info / create / ensure`，给推送脚本用 |
| 历史 GitHub Actions | `.github/workflows/build.yml` | 原样保留（GitHub 镜像仍可用），Gitee 侧不生效 |

```powershell
# 0) 迁移：建仓 + 推送（只需要一个私人令牌，勾 projects 权限）
$env:GITEE_TOKEN = "你的 Gitee 私人令牌"
pwsh -File ci\push_to_gitee.ps1

# 1) 全流程
pwsh -File ci\run_pipeline.ps1 -Stage all

# 2) 已有工作区，只打包 + 发布
pwsh -File ci\run_pipeline.ps1 -Stage pack -Publish -Tag sh-20261110-1530
```

令牌只需勾 `projects` 权限；也可以直接调发布器：

```bat
python tools\gitee_release.py list
python tools\gitee_release.py create --tag sh-20261110 --title "XMAPort-SHALLOW 1110" ^
    --notes-file release\notes.md release\*.7z.001
```

启用 Gitee Go：仓库 → 服务 → Gitee Go → 新建流水线 → 选「仓库内 YAML」，
把 `ci/gitee-go.yml` 拷成 `.workflow/build.yml`（插件参数以网页端步骤面板为准）。

---

## 6. 目录结构

```
XMAPort-SHALLOW/
├─ XMAPort.py                 入口：Step 1-8 编排 + CLI + 自检
├─ config.ini                 合并配置（移植/精简/打包三段 + 资源镜像）
├─ tools/
│  ├─ make_hyper.py           移植核心（上游）
│  ├─ pack_partitions.py      erofs/ext4 打包（上游）
│  ├─ extract_img.py          镜像解包（上游）
│  ├─ slim.py                 14 Pro 应用清单 + 通用档位
│  ├─ shennong_patch.py       make.sh 的功能修补移植
│  ├─ assets.py               shennong_files 下载 / 校验 / 镜像链
│  ├─ gitee_release.py        Gitee Release 发布（替代 gh CLI）
│  ├─ gitee_repo.py           Gitee 建仓 / 查仓（OpenAPI）
│  ├─ stage_common.py         路径/配置/体积公共设施
│  ├─ device_profiles.py      shennong / madrid 档案（预算上限）
│  ├─ package_zip.py          super.zst + 卡刷包
│  ├─ apktool.jar / jre/      services.jar 签名补丁用
│  ├─ 7z / aria2c / lpmake / mkfs.erofs / zstd …
│  └─ flashtools.zip          卡刷包里的刷机脚本
├─ ci/
│  ├─ push_to_gitee.ps1       建仓 + 推送（迁移落地用）
│  ├─ run_pipeline.ps1        Windows 全流程脚本（本地 / runner 通用）
│  └─ gitee-go.yml            Gitee Go 流水线模板（轻量校验 + 源码包）
├─ tests/
│  ├─ test_stages.py          无 ROM 回归测试（合成数据）
│  └─ make_fixture.py         生成合成工作区，便于手动跑 slim/pack
├─ docs/
│  ├─ GITEE.md                Gitee 迁移说明（改了什么、为什么、还有什么要注意）
│  ├─ PORT_18PROMAX_TO_14PRO.md  18 Pro Max → 14 Pro 专项说明（预算/版本/刷写）
│  ├─ ARCHITECTURE.md         流水线设计 / 数据流 / 分区来源
│  ├─ USAGE.md                详细用法 + 排错
│  ├─ MIGRATION.md            make.sh 每一段 → Python 的对照表
│  └─ LIMITS.md               没移植过来的部分与原因
└─ .github/workflows/build.yml  Windows CI（GitHub 侧保留）：自检 → 拉资源 → 三阶段 → 发布
```

---

## 7. 与上游的差异 / 已知限制

* **没有搬运的部分**：`vendor_boot` 里 `first_stage_ramdisk/fstab.qcom` 的替换
  （依赖 Linux 版 magiskboot + cpio）、KernelSU 注入（ksud 仅 Linux）、
  S3 上传（私有仓库密钥）。`tools/shennong_patch.py` 会明确 `skip`，不会假装成功。
* **签名校验移除**是可选步骤（`enable_signature=true`），走 apktool + 内置 JRE；
  失败只记为 `fail`，不中断打包。
* **完美图标**是可选步骤（`enable_icons=true`），需要联网拉 Perfect-Icons 项目
  （镜像链：Gitee 镜像 → codeload → 加速前缀）。
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

## 8. 测试

```bat
python tests\test_stages.py        :: 精简/修补单元回归（合成数据 + 假资源）
python tests\test_payload_args.py  :: payload 分区过滤/并发/超时 参数测试
python tests\make_fixture.py       :: 生成合成工作区
python XMAPort.py --auto --stage slim --device shennong --offline
python XMAPort.py --auto --stage pack --device shennong
```

`test_stages.py` 覆盖 5 组删除清单、保护名单、9 个资源替换步骤、build.prop 统一
和 vendor 侧修补；`make_fixture.py` 用来手动验证「精简 → 打包 → 出 zip」全链路，
包括 split_ab 的 lpmake 参数与 auto-fit 重打包。

CI：Gitee 侧用 `ci/gitee-go.yml`（Linux，只跑语法/自检/单测/源码包）；
Windows 全流程用 `ci/run_pipeline.ps1`，会先跑 `--selftest`，再按 `stage`
拉资源并执行全流程，最后分卷上传 Gitee Release。

---

## 9. 免责声明 (Disclaimer)

* 版权与使用限制：本项目仅供个人学习与测试使用。ROM 版权归小米公司所有，请于下载后 24 小时内删除。

* 刷机风险警告：刷机有风险，操作需谨慎。以下操作均可能导致设备变砖、数据丢失或无法开机，请自行承担全部后果：

  device_platform 配置填写错误；

  device_size 设置大于实机物理容量；

  Super 分区相关配置异常；

  底包与移植包的大版本跨度太大。

* 测试状态：该项目尚未经过实机测试。

* 严禁商用：本项目严禁用于任何商业用途或售卖盈利。

* 如有侵权，联系本人删除。

---

## 10. 致谢

* [XMAPort](https://github.com/NorthStarK-Lvy/XMAPort)（MIT）：移植引擎、打包器、工具链。
* [14PRO_SHALLOW_ROM](https://github.com/XHR222/14PRO_SHALLOW_ROM)：14 Pro 精简清单、修补资源与刷机脚本。
* 主代码 MIT（见 `LICENSE`）；捆绑的第三方工具（7-Zip / aria2 / payload-dumper-go /
  erofs-utils / lpmake / zstd / apktool / JRE / flashtools）遵循各自原始许可。
