# make.sh → Python 对照表

`14PRO_SHALLOW_ROM/make.sh` 是按执行顺序写的 bash 脚本。合并版把它拆成
「精简」(`tools/slim.py`) 与「修补」(`tools/shennong_patch.py`) 两段，
下面是逐段映射，方便审阅与追上游更新。

| make.sh 段落 | 合并版实现 | 备注 |
| --- | --- | --- |
| `aria2c` 下载两包 | XMAPort Step 1 | 保留 XMAPort 的双行进度与整体重试 |
| `7zzs x` 解压 | XMAPort Step 2 | |
| `payload_extract` + `extract.erofs` | XMAPort Step 3/4 | 目标机 `vendor` 改为按需解包（`unpack_vendor_for_patch`） |
| KernelSU（ksud + magiskboot） | `step_kernelsu` → skip | ksud 是 Linux ELF；Windows 版不提供 |
| vendor_boot 的 fstab 替换 | **未实现** | 需要 magiskboot + cpio 重打包，见 LIMITS.md |
| `vendor/etc/fstab.qcom` | `step_fstab` | 资源 `fstab.qcom` |
| `product/overlay` | `step_overlay` | |
| `device_features` | `step_device_features` | |
| `displayconfig` | `step_displayconfig` | |
| PowerKeeper | `step_powerkeeper` | |
| MiAONService | `step_miaon` | |
| 统一 build.prop（`sed` 版本/日期/机型/构建者） | `step_build_props` | 只替换已存在的键，语义对齐 `sed s/…/…/` |
| 5 组 `find … -iname "*app*" -exec rm` | `slim.SHENNONG_GROUPS` | 见下方「偏差」 |
| 分辨率 560 | `step_density` | |
| aptX Lossless | `step_aptx` | 追加到 vendor/build.prop |
| 替换相机三卷 | `step_camera` | 按 1→2→3 顺序二进制拼接 |
| 相机标定 CameraTools | `step_camera` | 解压到 `product/app` |
| MSA 占位 | `step_msa` | |
| 开机动画 | `step_bootanimation` | |
| 完美图标（git clone + zip 重建） | `step_icons`（可选） | 用 zipfile 重建 icons / dynamicicons |
| 删 recovery-from-boot / install-recovery | `step_recovery_stub` | |
| `init.qcom.rc` 删 qti-testscripts | `step_init_qcom` | |
| 内置 TWRP | `step_firmware` | 解压到 `target_payload/firmware-update` |
| 添加刷机脚本 | `package_zip` | 展开 `tools/flashtools.zip` |
| services.jar 去签名校验 | `step_signature`（可选） | apktool 反编译 → smali 改 `const/4 vX, 0x0` → 重编译 |
| 拷贝 `$device/*` 到 images | pack 阶段的分区来源表 | |
| `fspatch/contextpatch` + `mkfs.erofs -zlz4hc,9` | `pack_partitions.py` | 权限/SELinux 由 fs_config + file_contexts 补全 |
| `lpmake … super:8321499136` | `create_super_img` + `_build_lpmake_cmd` | `super_style=split_ab` 复刻 `_a/_b` + `-F --virtual-ab`；`single` 为 XMAPort 原布局 |
| （预算不够时重打） | `auto_fit_super` | 用真实镜像大小复查，逐档精简并只重打受影响分区 |
| `zstd -12 super.img` | `package_zip._zstd_compress` | Windows 版 `zstd.exe`，或 Python 3.14 stdlib |
| `7z a …zip images/*` | `package_zip.build` | 固定 mtime，便于复现 |
| 按 md5 重命名 | `_rom_name` | `SHENNONG_ShalloW_<版本>_<md5[:10]>_<安卓>.0.zip` |

## 有意的偏差

1. **`"CatchLog""com.xiaomi.ugd"`**：bash 里两个相邻字符串会被拼成一个词
   `CatchLogcom.xiaomi.ugd`，永远匹配不到目录。合并版按作者本意拆成两个关键词。
2. **`system` / `Health` 这类短关键词**：仍按「目录名包含」匹配（与 make.sh 一致），
   但增加了 `HARD_KEEP_TOKENS`（相机/桌面/SystemUI/Settings/overlay/bootanimation…），
   避免把 `Settings` 之类误删。
3. **路径探测**：make.sh 里既有 `images/system/system/...` 也有 `images/product/app/...`；
   合并版用 `stage_common.content_root()` 自动判断分区内容根，兼容两种镜像布局。
4. **执行顺序**：make.sh 先删应用再换资源；合并版先跑 `slim.py` 再跑 `shennong_patch.py`，
   与 make.sh 顺序一致。`--no-slim` 时只跑修补。
5. **vendor**：make.sh 直接把 `$device/vendor` 覆盖进 images；合并版显式解包 vendor.img、
   修补、再 `pack_partitions.py` 重打包，保证 fs_config/file_contexts 正确。
6. **mi_ext**：make.sh 用底包；合并版默认 `mi_ext_source=target`，并保留 `source` 选项。
7. **zstd / 7z**：Linux 版 `zstd` 换成 Windows 版 exe；7z 用仓库自带的 26.02。
8. **super 布局**：make.sh 用 `_a/_b` + `-F --virtual-ab`；合并版默认
   `super_style=split_ab` 复刻它，并保留 XMAPort 的单 group 布局作为 `single`。
9. **预算 auto-fit**：make.sh 假定移植包已经能装进 7.75 GiB；合并版在打包后
   用真实镜像大小复查，超出时自动加档精简（18 Pro Max 通常需要这一步）。

## 上游更新时怎么跟

* 应用清单变了：只改 `tools/slim.py` 的 `SHENNONG_GROUPS`。
* 修补步骤变了：在 `tools/shennong_patch.py` 加一个 `step_*` 函数，注册到 `STEPS`
  与 `ALL_STEPS`；资源加到 `ASSETS`/`ASSET_STEPS`。
* XMAPort 主流程变了：`XMAPort.py` 的 Step 1-5 是上游原样代码；
  Step 6-8 是本项目新增，升级时保留 `stage_pack()` / `run_slim_stage()` 即可。
