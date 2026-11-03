# 小米 18 Pro Max → 小米 14 Pro 适配说明

本项目固定为这个方向：

| | 机型 | 代号 | 系统 | Android | 角色 |
| --- | --- | --- | --- | --- | --- |
| 源 | Xiaomi 18 Pro Max | `madrid` | HyperOS 4（OS4.0.x.XEOCNXM） | 17 | 提供 system / system_ext / product |
| 目标 | Xiaomi 14 Pro | `shennong` | HyperOS 3（OS3.0.310.0.WNBCNXM） | 16 | 提供 odm / vendor / vendor_dlkm / system_dlkm / 固件 |

> 两代 Android 的跨度（17 → 16）是这条路线最大的风险点，比体积更关键。
> 体积用精简和预算解决，VNDK/APEX 只能靠「选更接近的源包 + sync_apex + 实测」。

---

## 1. 体积：7.75 GiB 怎么来的

```
device_size (super)        = 8 321 499 136 B   (7.75 GiB，14PRO_SHALLOW_ROM 实机验证)
metadata 65536 × 3 slots   =   196 608 B
margin（对齐/余量）        = 67 108 864 B      (64 MiB)
--------------------------------------------------------------
usable                     = 8 254 193 664 B   (7.69 GiB)
```

三道闸门，取最小值：

1. `config.ini [packing] device_size`；
2. 底包 OTA 里 `dynamic_partitions_info.txt` 的 `super_partition_size=`；
3. `tools/device_profiles.py` 的 `shennong.budget`。

18 Pro Max 的 system/product 通常明显大于 7.75 GiB，所以打包阶段有 **两级精简**：

* Step 6（固定）：14PRO_SHALLOW_ROM 的 5 组应用清单 + `slim_tiers=media,preinstall`；
* Step 7（动态）：`auto_fit=true` 时，用**真实镜像大小**复查预算，超出就依次启用
  `auto_fit_tiers=apps,audio,media,preinstall`，只重打 `system/system_ext/product`，
  再复查，直到装得下或档位用尽。

`--dry-run`/`plan` 可以先看能省多少：

```bat
python tools\slim.py plan --top 30
python tools\slim.py apply --tier apps --dry-run
```

## 2. 硬件差异：14 Pro 专属补丁

18 Pro Max 的相机、屏幕、电池、覆盖层与 14 Pro 不同，直接开机大概率黑屏/相机崩。
Step 6 会用 `shennong_files/` 把 14 Pro 的整套配置换回去：

| 差异 | 补丁 |
| --- | --- |
| 相机（模组/算法不同） | 14 Pro `MiuiCamera.apk`（三卷拼接）+ `CameraTools` 标定 |
| 屏幕（2K 120Hz） | `displayconfig` 替换 + `persist.miui.density_v2=560` + 120Hz prop |
| 机型特性 | `device_features` 替换 |
| 主题/资源叠加 | `product/overlay` 替换 |
| 电量/注视感知 | `PowerKeeper` / `MiAONService` 替换 |
| 分区表 | `vendor/etc/fstab.qcom` 替换 |
| 广告服务 | `MSA` 占位包 |
| 开机动画 | 14 Pro `bootanimation.zip` |
| 版本信息 | build.prop 统一为底包版本 + `ro.product.product.name=shennong` |
| 恢复/OTA | 删除 `recovery-from-boot.p`、`install-recovery.sh`，内置 TWRP |

## 3. super 布局：照抄 X-MiPort 4.0.5 的成品包

用 `lpdumps` 读本机参考包 `F:\Rom\X-MiPort-4.0.5\images\super.img`，得到：

```
Metadata version: 10.2   slots: 3   flags: virtual_ab_device
Group: qti_dynamic_partitions_a (仅一个，最大 8321499136)
Partitions: mi_ext_a, odm_a, vendor_a, vendor_dlkm_a, system_a,
            system_dlkm_a, product_a, system_ext_a   (只有 _a，没有 _b)
```

对应的 lpmake 命令：

```
lpmake --metadata-size 65536 --super-name super --block-size 4096 \
  --partition system_a:readonly:SIZE:qti_dynamic_partitions_a --image system_a=system.img \
  ...（每个分区一个 _a）...
  --device super:8321499136 --metadata-slots 3 \
  --group qti_dynamic_partitions_a:8321499136 \
  --virtual-ab -F --output super.img
```

合并版默认 `super_style=split_ab` 完全复刻这套参数（`-F` 输出完整 raw 镜像，
`sparse=false`），TWRP 的 `update-binary` 和 Windows 线刷脚本都能直接刷。
XMAPort 原来的单 group 布局仍保留为 `super_style=single`，只建议做实验时用。

卡刷包结构也对齐参考包：`images/super.img.zst`、`images/*.img`、
`bin/android/{7zzs,zstd}`、`bin/Windows/*`、现生成的 `update-binary` 和
`X-MiPort-Flash.bat`。

## 4. 版本跨度（Android 17 → 16）

`make_hyper.py` 的 `sync_apex` 会把**底包**的 VNDK APEX / vintf manifest 同步进
**移植包**的 system_ext，让新 system 认识旧 vendor。这条必须保留：

```ini
is_skip_apex=false
```

仍然可能失败的情况：

* 源包 system 依赖 Android 17 才有的 HAL/服务，而 14 Pro vendor 是 16；
* 16KB page size 内核差异（18 Pro Max 新内核 vs 14 Pro 4KB）；
* APEX 版本回退导致 `linker`/`apexd` 起不来。

处理顺序：

1. 换一个**更早的 madrid OS4 包**（框架与 target 的差距更小）；
2. 换一个**更新的 shennong HyperOS 3 底包**（vendor 越新越好）；
3. 看 `adb logcat` / `dmesg` 定位是 `apexd`、`vold` 还是 SurfaceFlinger；
4. 确认不是精简删多了（用 `--no-slim` 跑一次对照）。

## 5. 体积/磁盘排错

打包完成后会打印预算；装不下时**不会**去写 7.75 GiB 的 super.img，而是直接给出：

```
partition           image     source tree     payload img
vendor          4.69 GiB        4.70 GiB        1.52 GiB   <-- 比 payload 大很多
```

* 如果 `vendor`/`odm` 比底包 payload 的 `vendor.img`/`odm.img` 大很多，
  说明底包拿错了（大概率不是 shennong）或解包目录被污染。
  超过 **2 倍**时流水线会直接中止（`_check_inflation`），不会继续 lpmake；
  `strict_target=true` 还会在下载前就用 target URL 的代号拦住这种情况。
* 如果 `system`/`product` 太大，依次加档：`auto_fit_tiers=apps,audio,ai,theme,media,preinstall`；
  `python tools\slim.py plan --top 30` 手工把大文件写进 `extra_remove`。
* 压缩从 `lz4hc,9` 换 `zstd,15` 通常还能再省 10~15%（打包更慢）。
* 磁盘：默认 `cleanup_intermediate=true`、`keep_super_img=false`；
  仍不足就删 `workspace/download_*`、`workspace/source_rom`、`workspace/target_rom`。

## 6. 刷写

```bat
:: 0) 确认 super 放得下（十六进制换算成十进制 >= 8321499136）
fastboot getvar partition-size:super

:: 1) 解压 SHENNONG_ShalloW_*.zip，Windows 下
FlashWindows.bat
:: 或者 TWRP 直接卡刷整个 zip

:: 2) 首次开机不要插 SIM/登录账号，先看能不能到桌面
```

建议全程保留一个可用的 TWRP / 底包线刷包，至少能回滚。

## 7. 与 14PRO_SHALLOW_ROM 的差异

* 输入从「已经移植好的卡刷包」变成「源 ROM + 底包」两个直链，移植在流水线内完成；
* 应用清单、资源替换、build.prop、lpmake 参数、zip 命名保持一致；
* KernelSU 与 vendor_boot 的 first-stage fstab 未搬（Linux 工具依赖），见
  [LIMITS.md](LIMITS.md)；
* 增加了预算 auto-fit、split_ab 布局开关、设备档案与自检。
