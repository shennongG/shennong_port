# 小米 17 Ultra → 小米 14 Pro 适配说明（主路线）

本项目的**主路线**是这一条：

| | 机型 | 代号 | 系统 | Android | 角色 |
| --- | --- | --- | --- | --- | --- |
| 源 | Xiaomi 17 Ultra | `nezha` | HyperOS 4（OS4.0.7.0.XPACNXM） | 17 | 提供 `system` / `system_ext` / `product` |
| 目标 | Xiaomi 14 Pro | `shennong` | HyperOS 3（OS3.0.310.0.WNBCNXM） | 16 | 提供 `odm` / `vendor` / `vendor_dlkm` / `system_dlkm` / 固件 |

> 这条路线的每个关键参数都不是「猜」出来的：仓库里带了
> [reference/rom6_reference.json](../reference/rom6_reference.json)，它是从一个
> **已经实机刷开过机**的成品包解析出来的基线，`tools/ref_check.py` 会在打包后
> 与它逐项比对（详见 [PARTITION_MAP.md](PARTITION_MAP.md)）。

---

## 1. 这条路线凭什么可信

基线取自成品包 `X-MiPort_Mi14Pro_OS4.0.7.0.XPACNXM_nezha_01d961cefc_17.zip`
（6.49 GiB）。它自己的刷机脚本里写着：

```
加密状态: Data解密
机型代号: SHENNONG
机型名称: Xiaomi 14 Pro
底包版本: OS3.0.310.0.WNBCNXM
移植机型: Xiaomi 17 Ultra
移植版本: OS4.0.7.0.XPACNXM
安卓版本: 17
```

也就是说：**源 = 17 Ultra / OS4.0.7.0.XPACNXM，底包 = 14 Pro / OS3.0.310.0.WNBCNXM**，
与本项目 `config.ini` 的默认值是同一对版本。这一点很重要——换任何一个版本，
`odm`/`vendor`/框架的差距都会变，移植结果就不等价了。

从同一个包里还能读出（`python tools\ref_check.py package D:\Rom6`）：

| 观察 | 数值 | 对本项目的意义 |
| --- | --- | --- |
| super 镜像 | 8 321 499 136 B raw（7.75 GiB） | `device_size` 直接取这个数 |
| metadata | v10.2 / 3 slots / 65536 B | `metadata_size=65536`、`metadata_slots=3` |
| header flags | `virtual_ab_device` | `virtual_ab=true` |
| 分区组 | 只有 `qti_dynamic_partitions_a`（上限 7.75 GiB） | `super_style=split_ab` |
| 分区命名 | 只有 `_a`，**没有 `_b`** | 打 `_b` 会让 super 直接翻倍装不下 |
| `odm_a` | 2.15 GiB | 底包 odm 原样沿用（不做精简） |
| `vendor_a` | 447.30 MiB | 底包 vendor，仅打补丁后重打包 |
| `mi_ext_a` | 101.24 MiB | `mi_ext_source=target`（取底包） |
| 分区合计 | 7.36 GiB，余量 399 MiB | 精简后必须落在这个量级 |
| 卡刷包镜像 | 40 个：`super.img.zst` + `boot`/`init_boot` 6 种 ROOT 变体 + TWRP + 31 个固件镜像 | 与 `package_zip.py` 现生成的清单一致 |
| ROOT 组件 | 7 个 apk（Magisk / APatch / FolkPatch / KernelSU / KernelSU-Next / SukiSU / Kitsune Mask） | `assets/root_images` + `RootManager/` |
| 刷机方式 | 线刷 bat + TWRP `update-binary` 二选一 | `Flash-Windows.bat` + `update-binary` 都现生成 |

详细的字节级分区表见 [PARTITION_MAP.md](PARTITION_MAP.md)。

---

## 2. 体积账：7.75 GiB 怎么分

```
device_size (super)        = 8 321 499 136 B   (7.75 GiB，真机与参考包一致)
metadata 65536 × 3 slots   =       196 608 B
margin（对齐/余量）        =    67 108 864 B   (64 MiB)
--------------------------------------------------------------
usable                     = 8 254 193 664 B   (7.69 GiB)
```

参考包实际用量（`lpdumps` 实测）：`odm 2.15` + `product 2.90` + `system 0.89`
+ `system_ext 0.85` + `vendor 0.44` + `mi_ext 0.10` + `*_dlkm 0.04` ≈ **7.36 GiB**，
剩 399 MiB。也就是说：

* 17 Ultra 的 `product` 是最大头（2.90 GiB ↑），精简最先动它；
* `system` 只有 909 MiB —— 说明 17 Ultra 的框架并没有比 14 Pro 底包大很多，
  真正的体积压力来自 `product`（预装/媒体/主题）与 `odm`（沿用底包，不可压）。

两道闸门：

1. **Step 6 固定精简**：14 Pro 应用清单 + `slim_tiers=media,preinstall`；
2. **Step 7 auto-fit**：用**真实镜像字节数**复查预算，超出就按
   `auto_fit_tiers=apps,audio,media,preinstall,ai,theme` 逐档删，只重打受影响分区。

装不下时**不会**去写一个 7.75 GiB 的坏 super，而是先报差异（见 §5）。

---

## 3. 硬件差异：14 Pro 专属补丁

17 Ultra 的相机模组、屏幕、电池、overlay 与 14 Pro 不同，直接开机大概率黑屏或相机崩。
Step 6 用 `assets/shennong_files/` 把 14 Pro 的整套配置换回去：

| 差异 | 补丁（`shennong_patch.py` 的 step） |
| --- | --- |
| 相机（模组/算法不同） | `step_camera`：14 Pro `MiuiCamera.apk`（三段拼接）+ `CameraTools` 标定 |
| 屏幕（2K 120Hz） | `step_displayconfig` + `step_density`：`persist.miui.density_v2=560`、`ro.vendor.display.default_fps=120` |
| 机型特性 | `step_device_features`：`product/etc/device_features/shennong.xml` |
| 主题/资源叠加 | `step_overlay`：整目录替换 `product/overlay` |
| 电量/注视感知 | `step_powerkeeper`、`step_miaon` |
| 广告服务 | `step_msa`：占位包 |
| 开机动画 | `step_bootanimation`：14 Pro `bootanimation.zip` |
| 分区表（AB 槽位布局） | `step_fstab`：`vendor/etc/fstab.qcom` |
| 版本信息 | `step_build_props`：统一成底包版本 + `ro.product.product.name=shennong` |
| 恢复/OTA | `step_recovery_stub`：删 `recovery-from-boot.p`、`install-recovery.sh` |
| aptX Lossless | `step_aptx`：追加到 `vendor/build.prop` |
| init 脚本 | `step_init_qcom`：删 `qti-testscripts` 引用 |

缺资源时该 step 记 `skip`（`--offline` 可用于先跑通流程），不会静默失败。

---

## 4. 版本跨度（Android 17 → 16）

这是比体积更关键的**风险点**：源包 system 是 Android 17 的框架，14 Pro 的
vendor 是 Android 16 的 HAL。

`make_hyper.py` 的 `sync_apex` 会把**底包**的 VNDK APEX / vintf manifest 同步进
**移植包**的 `system_ext`，让新 system 认识旧 vendor。所以：

```ini
is_skip_apex=false
```

可能失败的样子与处理顺序：

1. 卡第一屏 / 循环重启：先看 `adb logcat`、`dmesg`，定位 `apexd` / `vold` / SurfaceFlinger；
2. `apexd` 报版本不匹配：换一个**更接近底包**的 `nezha` OS4 包（例如 4.0.0.15 而非 4.0.7.0），
   或换一个**更新的 shennong HyperOS 3 底包**（vendor 越新越好）；
3. 相机/指纹/信号单点崩：多半是 `shennong_files` 没下来，或 `odm` 拿错（不是 shennong）；
4. 确认不是精简删多了：加 `--no-slim` 跑一遍对照。

> 16 KB page size：17 Ultra 的内核按 16 KB 对齐，14 Pro 是 4 KB。
> 本项目**不搬内核**（`boot`/`vendor_boot` 用底包），所以这条只影响 `vendor` 侧
> 二进制，不在移植范围内，但会限制「能不能把 17 Ultra 的某些 HAL 一起搬过来」。

---

## 5. 打包后自检（本项目相对「参考包」的增量）

参考包是人肉试出来的；本项目把它变成可执行的检查：

```bat
:: 打包末尾自动跑（config.ini: verify_after_pack=true / strict / false）
python shennong_port.py --auto --device shennong

:: 也可以单独跑，或指定任意成品包/镜像
python shennong_port.py --verify
python shennong_port.py --verify --verify-path D:\Rom6
python tools\ref_check.py super workspace\packed\super.img
python tools\ref_check.py package workspace\output\shennong_unpacked
```

比对内容（失败即 `fail`，会让 `verify_after_pack=strict` 的构建直接判失败）：

* super 文件大小 ≤ 基线，`block device super` 大小 **必须** 等于 8 321 499 136；
* `metadata` 版本 / 槽位 / 逻辑块大小 / `virtual_ab_device` 标志；
* 分区组名与上限（`qti_dynamic_partitions_a`）；
* 8 个 `_a` 分区是否齐全、每个分区的字节数与基线的偏差、**不允许出现 `_b`**；
* 卡刷包里的机型代号 / 机型名 / 底包版本是否与基线一致。

---

## 6. 刷写顺序（照参考包实测的顺序）

```
1) fastboot getvar unlocked           -> yes（未解锁就别刷）
2) fastboot getvar partition-size:super -> 必须 >= 8321499136
3) 选 ROOT：NoROOT / Magisk / APatch / FolkPatch / KernelSU / SukiSU / KernelSU-Next / Kitsune Mask
4) boot_ab + init_boot_ab             （按 ROOT 选择配对）
5) recovery_ab（可选 TWRP）
6) 31 个固件镜像：xbl / xbl_config / xbl_ramdump / aop / aop_config / abl / tz /
   hyp / devcfg / dsp / keymaster / qupfw / shrm / cpucp / cpucp_dtb /
   featenabler / imagefv / uefi / uefisecapp / multiimgqti / modem / modemfirmware /
   bluetooth / spuservice / dtbo / vm-bootsys / vendor_boot / vbmeta(+--disable-verity
   --disable-verification) / vbmeta_system
7) fastboot flash super images/super.img   （刷完可能卡一会儿，别急着重启）
8) 首次刷入：fastboot erase userdata / metadata
9) fastboot set_active a
10) fastboot reboot
```

`Flash-Windows.bat` 与 TWRP 的 `update-binary` 都是流水线现生成的，顺序与上面一致；
TWRP 侧还会**先用文件名里的 MD5 前 10 位校验整个 zip**，不匹配直接退出（防半包）。

建议全程保留一个可用的底包线刷包 / TWRP，随时能回滚。

---

## 7. 与另一条路线（18 Pro Max）的差别

| | 17 Ultra（本路线，已验证） | 18 Pro Max（candidate） |
| --- | --- | --- |
| 源版本 | OS4.0.7.0.XPACNXM | OS4.0.27.0.XEOCNXM |
| 底包 | OS3.0.310.0.WNBCNXM | 同 |
| 有没有成品包基线 | **有**（Rom6） | 无（只有 `madrid` 档案） |
| `product` 体积 | 参考包 2.90 GiB | 更大，auto-fit 档位要更狠 |
| 默认 | ✅ `config.ini` 就是这条 | 换 `[source] url` 即可 |

两条路线共用同一套流水线；`tools/device_profiles.py` 的 `ROUTES` 表记录状态，
`--selftest` 会打印当前是哪条路线、有没有基线。
