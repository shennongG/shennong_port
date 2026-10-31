# 使用与排错

## 1. 环境

| 项 | 要求 |
| --- | --- |
| 系统 | Windows 10 / 11 64 位（工具链是 Windows 版；Linux 需自行替换 exe） |
| Python | 3.8+（建议 3.12；3.14 可用 stdlib zstd 兜底） |
| 磁盘 | 约 40 GB（下载 + 解包 + 打包中间产物） |
| 网络 | 能访问 GitHub（资源）与小米 OTA 直链（ROM） |

仓库自带 `tools/` 下的 7z、aria2c、payload-dumper-go、extract.erofs、mkfs.erofs、
lpmake、lpdumps、apktool.jar、JRE、zstd、flashtools.zip，无需另装。

## 2. 配置重点

```ini
device_platform=Qualcomm      ; 14 Pro = SM8650；填错变砖
device_size=8321499136        ; 7.75 GiB，必须 <= 实机 super
pack_super=true               ; 预算约束依赖它
super_style=split_ab          ; 14 Pro 验证过的 _a/_b 布局
sparse=false                  ; TWRP/fastboot 脚本吃 raw
super_group=qti_dynamic_partitions

[source] url=…                ; 18 Pro Max (madrid) 完整 OTA
[target] url=…                ; 14 Pro (shennong) 底包完整 OTA

[shennong] enable=true
[slim] slim_tiers=media,preinstall
auto_fit=true                 ; 打包后按真实大小再收敛
auto_fit_tiers=apps,audio,media,preinstall
```

版本号（`OS4.0.27.0.XEOCNXM` 之类）不用填，流水线会从 URL 路径和 build.prop 自动解析。
`--selftest` 会打印 donor/target 的代号、Android 版本和可用预算，方向填反会提示。

## 3. 一次完整运行

```bat
python XMAPort.py --selftest
python tools\assets.py fetch
python XMAPort.py --auto --device shennong
```

中间想停/改：

```bat
python XMAPort.py --auto --device shennong --stage port
python tools\slim.py plan --top 30          :: 看还能砍什么
:: 改 config.ini 的 slim_tiers / extra_remove
python XMAPort.py --auto --device shennong --stage slim
python XMAPort.py --auto --device shennong --stage pack
```

> `--stage slim` / `--stage pack` 需要工作区已存在（至少 `source_filesystem`）。
> `--stage pack` 会重新打包所有分区，所以手工改过文件后直接跑它即可。

## 4. 常用调试命令

```bat
:: 只体检精简清单，不删东西
python tools\slim.py plan --top 30
python tools\slim.py apply --tier media --dry-run

:: 只跑修补（不联网，缺资源就跳过）
python tools\shennong_patch.py apply --dry-run --offline
python tools\shennong_patch.py list

:: 单分区重打包（改完文件后）
python tools\pack_partitions.py erofs lz4hc,9 workspace\source_filesystem\product workspace\packed

:: 用 packed 里现成镜像重新合成 super（等价主菜单 [A]）
python XMAPort.py      :: 然后按 A -> 1

:: 只出 zip（super.img 已存在）
python tools\package_zip.py
```

## 5. 产物与刷写

```
workspace/packed/super.img
workspace/output/SHENNONG_ShalloW_<版本>_<md5>_<安卓>.0.zip
```

* Windows 线刷：解压 zip，运行 `FlashWindows.bat`（要求 `fastboot getvar product` 为 `shennong`）。
* Recovery 卡刷：整个 zip 进 TWRP 安装（`META-INF/com/google/android/update-binary`）。
* 刷前确认：`fastboot getvar partition-size:super` ≥ `8321499136`（十六进制 `0x1F0000000`）。

## 6. 排错

**Q：CI 报 `There is not enough space on the disk` / `7z 打包失败 (rc=2)`？**
两套 ROM 解压后 + 7.75 GiB raw super + zst + zip 很容易超过 runner 磁盘。
本版已默认：

* `cleanup_intermediate=true`：Step 2 解压完删 OTA zip，Step 3 解包完删
  `source_rom/`、`target_rom/`（合计能省 30 GB 左右）；
* `keep_super_img=false`：zip 成功后删除 7.75 GiB raw `super.img`；
* lpmake 之前先做预算判断，装不下直接停，不会白写 7.75 GiB；
* 只有 lpmake 成功才做 zip，避免拿半个 super 去压缩。

还报错时按顺序手动删：`workspace/download_source`、`workspace/download_target`、
`workspace/source_rom`、`workspace/target_rom`、`workspace/package_stage`。

**Q：`--selftest` 报缺 tools/xxx？**
解压不完整，或用了旧版仓库。重新拉取仓库（`tools/` 必须完整，含 `jre/`、`flashtools.zip`）。

**Q：资源下载卡住 / 403？**
换镜像：`config.ini [shennong] asset_base=…` 或 `set SHENNONG_ASSET_BASE=…`。
也可手动把 13 个文件放进 `assets/shennong_files/`，`python tools/assets.py verify` 校验大小。

**Q：精简后缺功能 / 相机异常？**
`tools/slim.py` 只删清单内目录；相机、桌面、SystemUI 有硬保护。若手工 `extra_remove`
删多了，从 `--stage port` 重来（会重新解包覆盖）。

**Q：`lpmake` 报空间不足？**
1. 调小 `margin_mib`（64 → 32）；
2. `slim_tiers=media,preinstall,apps,audio`；
3. `compression_level` 9 → 12，或 `compression=zstd`；
4. `python tools\slim.py plan --top 40` 手工点名大文件写进 `extra_remove`。

**Q：刷完卡在开机动画 / 第二屏？**
18 Pro Max 是 Android 17，14 Pro 底包是 Android 16，框架/VNDK 跨度是主因。
先换更早的 madrid OS4 包或更新的 shennong 底包；再确认 `is_skip_apex=false`
（sync_apex 要跑）；最后用 `--no-slim` 排除精简删多了。详见
[PORT_18PROMAX_TO_14PRO.md](PORT_18PROMAX_TO_14PRO.md)。

**Q：super.img 是 7.75 GiB 整？**
`super_style=split_ab` 用了 `-F`，lpmake 会输出完整 raw 镜像（14PRO 的刷机脚本要求）。
zip 里会先 `zstd` 压缩，体积由实际数据决定。

**Q：super.img 比 7.75G 小很多？**
`sparse=true` 时是稀疏文件，磁盘占用按实际数据算；判断预算要看
`slim.py check` 里的未稀疏字节数。默认 `sparse=false` 就是完整 raw。

**Q：zip 里没有 super.zst？**
说明 `tools/zstd.exe` 缺失且 Python < 3.14，已自动退回 `super.img`；不影响刷写，只是包更大。

**Q：vendor 修补没生效？**
检查 `repack_vendor=true`、`target_payload/vendor.img` 是否存在；
`unpack_vendor_for_patch()` 解包失败时日志会写 `WARNING: vendor.img not found`。

**Q：想把 mi_ext 换成移植包的？**
`config.ini [packing] mi_ext_source=source`。

## 7. 占用清理

```bat
:: 保留工作区（推荐，便于 --stage slim/pack 续跑）
python XMAPort.py    :: 菜单 D 会删整个 workspace

:: 只删打包中间产物
rmdir /s /q workspace\package_stage
del workspace\rom_tmp.zip
```
