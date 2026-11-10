# 实现步骤对照（Step → 模块 → 判定）

本项目的流水线按 8 个 Step 串行，每个 Step 都落在一个明确的模块里，
这样断点续跑（`--stage`）、单测和排错都能精确定位。下表是「做什么 / 谁来做 /
怎么算完成」，最后附上几处刻意的行为偏差。

## 1. 总览

| Step | 模块 | 产出 |
| --- | --- | --- |
| 1 下载 | `shennong_port.py`（aria2c 并行） | `workspace/download_*/` |
| 2 解包 payload | `tools/extract_payload*` + `payload-dumper-go` | `workspace/*_payload/*.img` |
| 3 展开文件系统 | `tools/extract_img.py` | `workspace/*_filesystem/<分区>/` |
| 4 迁移 | `tools/make_hyper.py` | 目标分区的雏形（system / system_ext / product） |
| 5 补丁 | `tools/make_hyper.py` + `tools/patch_*` | 版本对齐、vbmeta 禁验、fstab 等 |
| 6 精简 / 修补 | `tools/slim.py` + `tools/shennong_patch.py` | 精简后的分区 + 资源替换结果 |
| 7 打包分区 | `tools/pack_partitions.py` | `workspace/packed/*.img` |
| 8 合成 + 出包 | `workspace/packed/super.img` + `tools/package_zip.py` | `workspace/output/*.zip` |

## 2. 精简 / 修补明细

| 动作 | 实现 | 判定 |
| --- | --- | --- |
| 5 组应用清单删除 | `slim.SHENNONG_GROUPS` | 目录名包含关键词即整棵删除；`HARD_KEEP_TOKENS` 与 `slim_keep` 优先 |
| 预算收敛 | `slim` + `auto_fit_super` | 用真实镜像字节数复查 `usable`，超出即按 `auto_fit_tiers` 逐档精简、只重打受影响分区 |
| `vendor/etc/fstab.qcom` | `step_fstab` | 资源 `fstab.qcom` 覆盖后计数 |
| `product/overlay` | `step_overlay` | 目录整体替换 |
| `device_features` / `displayconfig` | 同名 step | 解压到 `product/etc/*` |
| PowerKeeper / MiAONService / MSA | `step_powerkeeper`、`step_miaon`、`step_msa` | 目录替换，缺资源则 `skip` |
| 相机三卷 + 标定 | `step_camera` | 1→2→3 顺序二进制拼接成 `MiuiCamera.apk`，标定解压到 `product/app` |
| 开机动画 | `step_bootanimation` | `product/media/bootanimation.zip` |
| 版本 / 日期 / 机型 / 构建者 | `step_build_props` | 只替换已存在的 `key=`，不凭空追加 |
| 密度 560 | `step_density` | 写 `product/etc/build.prop` |
| aptX Lossless | `step_aptx` | 追加到 `vendor/build.prop` |
| 删 `recovery-from-boot.p` / `install-recovery.sh` | `step_recovery_stub` | 文件不存在也算完成 |
| `init.qcom.rc` 删 `qti-testscripts` | `step_init_qcom` | 行级删除，保留其余内容 |
| 内置 TWRP | `step_firmware` | 解压到 `target_payload/firmware-update` |
| 刷机脚本 | `package_zip` | 展开 `tools/flashtools.zip`，删掉自带的 `.bat` 后现生成 |
| services.jar 去签名校验（可选） | `step_signature` | apktool 反编译 → smali 改 `const/4 vX, 0x0` → 回编译；失败只记 `fail` |
| 图标包（可选） | `step_icons` | 下载 → 重建 `icons.zip` / `dynamicicons.zip` |

## 3. 打包明细

| 动作 | 实现 | 判定 |
| --- | --- | --- |
| erofs 重打包 | `pack_partitions.py` | 权限 / SELinux 由 `fs_config` + `file_contexts` 补全 |
| super 合成 | `create_super_img` / `_build_lpmake_cmd` | 只有 `<part>_a`、单 group、`-F --virtual-ab`、`device_size=8321499136`、raw |
| 压缩 | `package_zip._zstd_compress` | 优先 `zstd.exe -12`，退路是 Python 3.14 的 `compression.zstd` |
| 卡刷包 | `package_zip.build` | `images/super.img.zst` + 固件 + `bin/` + 现生成脚本 + `NOTICE/` |
| 命名 | `_rom_name` | `ShennongPort_Mi14Pro_<版本>_<donor>_<md5[:10]>_<安卓>.zip` |

## 4. 刻意的行为偏差

1. **只做 Windows 能做完的事**：`vendor_boot` 里 `first_stage_ramdisk/fstab.qcom`
   的替换、KernelSU 注入（ksud）都依赖 Linux 工具链，代码里明确 `skip` 并写日志，
   不静默失败（见 [LIMITS.md](LIMITS.md)）。
2. **属性替换只改已存在的键**：等价于逐行 `s/old/new/`，不会给 build.prop 追加
   原本没有的字段，避免启动脚本读不到默认值。
3. **删除清单有保护名单**：`system`、`app` 这类短关键词容易误伤 `Settings`、
   `SystemUI`，所以 `HARD_KEEP_TOKENS` 优先于删除清单。
4. **预算先收敛再打包**：`auto_fit` 用真实镜像大小复查，宁可少打几个分区，
   也不留一个装不进 super 的包。
5. **每一步都记状态**：`workspace/slim_state.json` 里有每步的 `ok / skip / fail`
   与原因，`--stage` 续跑时直接读它。
