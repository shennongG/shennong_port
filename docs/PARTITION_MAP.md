# 分区布局基线（来自 Rom6 完美包实测）

> 数据来源：`D:\Rom6\images\super.img`，由 `python tools\ref_check.py super <img>`
> 解析 liblp 元数据得到（与 `tools\lpdumps.exe` 输出逐字段一致）。
> 基线文件：[reference/rom6_reference.json](../reference/rom6_reference.json)　｜　比对工具：[tools/ref_check.py](../tools/ref_check.py)

## 1. super 元数据

| 项 | 值 |
| --- | --- |
| 文件大小 | 8,321,499,136 B（7.75 GiB） |
| metadata 版本 | 10.2 |
| metadata 大小上限 / 槽位 | 65536 B / 3 |
| 逻辑块大小 | 4096 B |
| header flags | `virtual_ab_device` |
| 分区组 `default` 上限 | 0 B |
| 分区组 `qti_dynamic_partitions_a` 上限 | 8,321,499,136 B |
| 分区合计 | 7,902,806,016 B（7.36 GiB） |
| 剩余（对齐 + 余量） | 418,693,120 B（399.30 MiB） |

## 2. 分区表

| # | 分区 | 字节数 | MiB | GiB | 起始扇区 | 分区组 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `mi_ext_a` | 106,156,032 | 101.24 | 0.099 | 2048 | `qti_dynamic_partitions_a` |
| 2 | `odm_a` | 2,306,400,256 | 2199.55 | 2.148 | 210944 | `qti_dynamic_partitions_a` |
| 3 | `vendor_a` | 469,032,960 | 447.30 | 0.437 | 4716544 | `qti_dynamic_partitions_a` |
| 4 | `vendor_dlkm_a` | 30,826,496 | 29.40 | 0.029 | 5634048 | `qti_dynamic_partitions_a` |
| 5 | `system_a` | 953,421,824 | 909.25 | 0.888 | 5695488 | `qti_dynamic_partitions_a` |
| 6 | `system_dlkm_a` | 14,934,016 | 14.24 | 0.014 | 7559168 | `qti_dynamic_partitions_a` |
| 7 | `product_a` | 3,109,855,232 | 2965.79 | 2.896 | 7589888 | `qti_dynamic_partitions_a` |
| 8 | `system_ext_a` | 912,179,200 | 869.92 | 0.850 | 13664256 | `qti_dynamic_partitions_a` |

> 只有 `_a` 后缀、只有一个 `qti_dynamic_partitions_a` 组、`--virtual-ab`：
> 这是 14 Pro 参考包在真机上验证过的布局，本项目 `super_style=split_ab` 与之一致。

## 3. 卡刷包镜像清单（同类文件）

| 组 | 文件 | 字节数 |
| --- | --- | ---: |
| boot / init_boot（ROOT 变体） | `boot.img` | 100,663,296 |
| boot / init_boot（ROOT 变体） | `boot_apatch.img` | 100,663,296 |
| boot / init_boot（ROOT 变体） | `boot_folkpatch.img` | 100,663,296 |
| boot / init_boot（ROOT 变体） | `init_boot_kitsune-mask.img` | 8,388,608 |
| boot / init_boot（ROOT 变体） | `init_boot_ksu-next.img` | 8,388,608 |
| boot / init_boot（ROOT 变体） | `init_boot_ksu.img` | 8,388,608 |
| boot / init_boot（ROOT 变体） | `init_boot_magisk.img` | 8,388,608 |
| boot / init_boot（ROOT 变体） | `init_boot_official.img` | 8,388,608 |
| boot / init_boot（ROOT 变体） | `init_boot_sukisu.img` | 8,388,608 |
| recovery | `recovery.img` | 104,857,600 |
| recovery | `recovery_twrp.img` | 104,857,600 |
| vbmeta | `vbmeta.img` | 8,192 |
| vbmeta | `vbmeta_system.img` | 4,096 |
| 基带 / 固件 | `bluetooth.img` | 1,470,464 |
| 基带 / 固件 | `dsp.img` | 67,108,864 |
| 基带 / 固件 | `modem.img` | 130,019,328 |
| 基带 / 固件 | `modemfirmware.img` | 237,260,800 |

## 4. 复算命令

```bat
:: 直接读任意 super.img 的分区表（不需要 lpdumps.exe）
python tools\ref_check.py super workspace\packed\super.img

:: 审计一个解压后的卡刷包目录（镜像齐不齐、版本对不对、布局是否一致）
python tools\ref_check.py package D:\Rom6

:: 生成/刷新基线（换路线或换底包后必须重做）
python tools\ref_check.py emit D:\Rom6 --emit reference\rom6_reference.json
```
