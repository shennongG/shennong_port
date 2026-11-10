# 架构说明

## 1. 数据流

```
             config.ini ([source] / [target])
                      │
        ┌─────────────▼──────────────┐
        │ Step 1  aria2c 双包并行下载 │
        └─────────────┬──────────────┘
                      │  download_source/  download_target/
        ┌─────────────▼──────────────┐
        │ Step 2  7z 解压 OTA zip     │
        └─────────────┬──────────────┘
                      │  source_rom/  target_rom/
        ┌─────────────▼──────────────┐
        │ Step 3  payload-dumper-go   │
        └─────────────┬──────────────┘
                      │  source_payload/*.img  target_payload/*.img
        ┌─────────────▼──────────────┐
        │ Step 4  extract.erofs / ext4│
        └─────────────┬──────────────┘
                      │  source_filesystem/{system,system_ext,product,mi_ext}
                      │  target_filesystem/{odm,vendor,…} + config/*_fs_config
        ┌─────────────▼──────────────┐
        │ Step 5  make_hyper.py speed │  迁移 / 设备特性 / 相机 / apex / build.prop
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │ Step 6  slim + shennong    │  删应用 + 换资源 + 改属性 + vendor 修补
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │ Step 7  pack + zip          │  erofs + lpmake + zstd + 7z
        └─────────────┬──────────────┘
                      │
        workspace/packed/*.img  super.img
        workspace/output/SHENNONG_ShalloW_*.zip
```

## 2. 分区来源

| 分区 | 来源 | 打包方式 |
| --- | --- | --- |
| `system` / `system_ext` / `product` | 移植包（源 ROM） | 精简后用 `mkfs.erofs` 重新打包 |
| `mi_ext` | 底包（默认）或源包（`mi_ext_source=source`） | 直接复制镜像 |
| `odm` | 底包 | 重新打包 `target_filesystem/odm` |
| `vendor` | 底包，但被 14 Pro 修补过 | 解包 → 修补 → 重新打包 |
| `vendor_dlkm` | 底包 | 直接复制 |
| `system_dlkm` | 底包（存在才加） | 直接复制 |
| `vbmeta*` | 底包 | 复制 + 禁验 |

> 早期实现把 `mi_ext/odm/vendor/vendor_dlkm/system_dlkm` 全部取自底包；
> 本项目默认沿用（`mi_ext_source=target`），同时保留 `mi_ext_source=source` 选项。

## 3. super 预算与布局

```
budget = min(config.device_size, 底包 dynamic_partitions_info.txt 的 super_partition_size,
             tools/device_profiles.py 里 shennong 的上限)
usable = budget - metadata_size × metadata_slots - margin
```

默认 `budget = 8 321 499 136`（7.75 GiB），`metadata 65536 × 3`，`margin 64 MiB`。

打包分两步收敛：

1. **Step 6 固定精简**：14 Pro 应用清单 + `slim_tiers=media,preinstall`；
2. **Step 7 auto-fit**：所有镜像打包完成后，用真实字节数复查 `usable`；超出就按
   `auto_fit_tiers` 逐档删除并只重打 `system/system_ext/product`，直到装得下。

super 布局由 `super_style` 决定：

* `split_ab`（默认）：14 Pro 参考成品包在 shennong 验证过的布局 ——
  只有 `<name>_a`、单 group `qti_dynamic_partitions_a`、
  `-F --virtual-ab`，raw 输出（`sparse=false`）；
* `single`：ShennongPort 原始的单 group 布局，仅用于实验。

`lpmake` 返回「空间不足」时，ShennongPort 原有兜底会跑 `make_hyper.py extreme` 并只重打 product。

## 4. 模块边界

| 模块 | 输入 | 输出 | 依赖 |
| --- | --- | --- | --- |
| `slim.py` | `workspace/source_filesystem` | 删除后的目录树 + `slim_state.json` | 只读 config |
| `shennong_patch.py` | 源/目标文件系统 + `assets/shennong_files` | 修补后的目录树 + `shennong_patch.json` | `assets.py` |
| `package_zip.py` | `workspace/packed/super.img` + `target_payload` | `workspace/output/*.zip` | `7z.exe` / `zstd.exe` |
| `stage_common.py` | — | 路径 / 配置 / 体积 / 安全删除 | 无 |

三个模块都能单独 CLI 运行，便于排错：

```bat
python tools\slim.py plan --top 20
python tools\slim.py apply --tier media --dry-run
python tools\shennong_patch.py list
python tools\shennong_patch.py apply --dry-run --offline
python tools\package_zip.py --dry-run
```

## 5. 失败策略

| 阶段 | 失败时 |
| --- | --- |
| 下载 / 解包 / 迁移 | 立即中止（`_abort_port`），不产生半成品 super |
| 精简删除 | 单条失败会记录并继续，最终返回 1 |
| 修补步骤 | 缺资源的步骤 `skip`；抛异常的步骤 `fail`，打包仍继续（结果里可见） |
| 分区打包 | 统计 `pack_fail`，汇总标红 |
| super / zip | `super_rc != 0` 或 zip 失败 → 整体退出码 1 |

日志：`workspace/<日期>-<小时>.log`；另有 `slim_state.json`、`shennong_patch.json`、
`output/*.json` 三份结构化记录。
