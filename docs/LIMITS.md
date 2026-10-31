# 已知限制 / 未覆盖项

合并版的目标是「一条命令跑完 移植→精简→打包」，并没有假装移植 make.sh 的每一行。
下面这些部分**没有**搬过来，代码里会明确 `skip` 并写日志，不会静默失败。

## 1. vendor_boot 的 first_stage_ramdisk/fstab.qcom

make.sh 用 `magiskboot unpack` + `cpio` 解出 `vendor_boot.img → ramdisk`，
替换 `first_stage_ramdisk/fstab.qcom` 后重新压缩/封包。这一步需要：

* Linux 版 `magiskboot`（Windows 版不可用）；
* `cpio` / lz4 / gzip 压缩器；
* 对 `vendor_boot` 头部（`-h`）的正确处理。

**影响**：`vendor/etc/fstab.qcom` 已经替换（挂载表在 vendor 内生效），
但 first-stage 仍用底包原 fstab。多数情况下这两份内容一致；
若底包与移植包的分区布局差异很大，可能卡 first stage。

**手动做法**：在 Linux（或 WSL）里按 make.sh 那一段执行一次，或
`fastboot flash vendor_boot vendor_boot-patched.img`。

## 2. KernelSU 注入

`ksud boot-patch -b init_boot.img --magiskboot … --kmi android14-6.1` 只有 Linux 二进制。
副作用：卡刷包的 `FlashWindows.bat` 里选 `KSU=y` 会找 `firmware-update/init_boot-kernelsu.img`，
本流水线不生成该文件；选 `n` 则刷原版 `init_boot.img`，一切正常。

**手动做法**：Linux 下跑 ksud 生成 `init_boot-kernelsu.img`，放进
`workspace/target_payload/firmware-update/` 后重跑 `--stage pack`。

## 3. services.jar 去签名校验（可选）

`step_signature` 已实现（apktool 反编译 → 替换
`getMinimumSignatureSchemeVersionForTargetSdk` 的返回值 → 重编译），但默认关闭：

* 依赖 `tools/jre` + `tools/apktool.jar`（仓库自带）；
* 处理 8 GB 分区时 apktool 会额外吃内存与时间；
* 改坏 services.jar 会直接卡开机。

开启方式：`[shennong] enable_signature=true`，或
`python tools\shennong_patch.py apply --steps signature`。

## 4. 完美图标（可选）

`step_icons` 会联网拉 `pzcn/Perfect-Icons-Completion-Project`，重建
`product/media/theme/default/icons` 与 `dynamicicons`。默认关闭，因为：

* 需要访问 GitHub；
* 图标包更新后布局可能变化，需要人工确认。

`[shennong] enable_icons=true` 开启。

## 5. 云上传

上游 14PRO 的 workflow 里有 Oracle S3 上传（依赖私有 `secrets.confbase64`），
合并版的 CI 只发 GitHub Release。

## 6. 真机验证

没有 14 Pro 实机，也没有实际下载十几 GB 的 ROM。已完成的验证：

* `python XMAPort.py --selftest`（工具链/模块/配置）；
* `tests/test_stages.py`（合成数据覆盖精简与修补）；
* 合成工作区端到端跑通 `--stage slim` + `--stage pack`：
  `mkfs.erofs` 实际打包、`lpmake` 实际生成 sparse super、`zstd` + `7z` 实际出 zip。

未验证：真实 ROM 的解包兼容性、迁移后的开机、相机/指纹/基带等功能。

## 7. Android 17 → 16 的跨度

18 Pro Max 是 HyperOS 4 / Android 17，14 Pro 底包是 HyperOS 3 / Android 16。
`sync_apex` 会把底包 VNDK APEX / vintf 同步进移植包，但以下情况仍可能起不来：

* system 侧依赖 Android 17 新增的 HAL / 系统服务；
* 16KB page size 内核与传统 4KB vendor 的差异；
* 源包某个 APEX 版本比底包低，`apexd` 回退失败。

这不是本仓库能靠代码消除的，只能换更接近的源包/底包并看 logcat。
预算与精简只解决「装得下」，不解决「跑得动」。

## 8. 其他小差异

* `make.sh` 里 `sudo find … -iname "*x*"` 是「任意层级目录」；合并版只在这些分区的
  指定子目录下递归，范围更保守。
* `bootanimation.zip`、`wallpaper` 等被通用档位 `media` 删除时不受保护名单限制
  （应用清单删除仍受保护），因为 `media` 档位就是显式要删它们。
* zip 内文件 mtime 固定为 2009-01-01（对齐 make.sh 的 `touch -t`），
  但 super.img 内部时间戳仍由 `mkfs.erofs -T` 决定，`utc_stamp` 留空时每次不同。
