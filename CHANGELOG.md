# 更新日志

本项目遵循「一条路线一版」的节奏：换源机型 / 换底包 / 换 super 布局都算一个版本。
日期格式 `YYYY-MM-DD`。

## v0.4.0 — 2026-11-17

**主路线切换到 小米 17 Ultra（`nezha`）→ 小米 14 Pro（`shennong`），并把「完美包」变成可执行的基线。**

### 新增

* `reference/rom6_reference.json`：从已实机刷开机的 17 Ultra → 14 Pro 成品包
  （`X-MiPort_Mi14Pro_OS4.0.7.0.XPACNXM_nezha_*.zip`）解析出的基线——
  super 8 321 499 136 B、metadata v10.2 / 3 slots、`virtual_ab_device`、
  单 group `qti_dynamic_partitions_a`、8 个 `_a` 分区的字节数与起始扇区、
  卡刷包镜像/ROOT 组件清单、机型与版本信息。
* `tools/ref_check.py`：**纯标准库**的 liblp 解析 + 卡刷包审计 + 基线比对。
  * `super <img>`：不装 `lpdumps.exe` 也能读出分区表（容错解析：描述符基址
    `+24`/`+80`、magic 在 8192 或 12288 的厂商布局都能识别）；
  * `package <目录>`：镜像齐不齐、版本号/代号对不对、布局是否与基线一致；
  * `emit <目录> --emit ref.json`：用任意成品包生成/刷新基线。
* `shennong_port.py --verify` / `--verify-path`：只跑基线比对，可对任意 super.img
  或解压后的卡刷包目录。
* Step 7.9：打包完成后自动比对（`verify_after_pack=true|strict|false`）。
* `docs/PORT_NEZHA_TO_14PRO.md`：主路线说明，含 Rom6 证据链、体积账、硬件补丁表、
  Android 17 → 16 跨度处理、刷写顺序。
* `docs/PARTITION_MAP.md`：基线分区表（字节级，附复算命令）。
* `tests/test_ref_check.py`：15 个用例（合成 super、描述符基址后移、备 geometry
  布局、缺分区/超预算/多出 `_b` 判定、混排编码脚本、emit→compare 闭环、
  真实成品包端到端）。
* `tools/device_profiles.py`：新增 `nezha` 档案与 `ROUTES` 路线表
  （`nezha → shennong` = verified，`madrid → shennong` = candidate），
  `--selftest` 会打印当前路线与基线状态。

### 变更

* `config.ini` 默认源包改为 `nezha`（`OS4.0.0.15.XPACNXM` 直链已核验可达，
  注释里给出与参考包完全对齐的 `OS4.0.7.0.XPACNXM` 写法）；底包仍为
  `shennong / OS3.0.310.0.WBNCNXM`（与参考包一致）。
* 自检输出增加：路线状态、参考基线分区数、Android 跨度提示指向新文档。
* 文档（README / ARCHITECTURE / STEPS）同步：新增「参考基线比对」章节与
  Step 7.9 的失败策略。

### 说明

* 基线校验的是**布局与版本**（能不能装进 super、刷机脚本认不认），
  不等于「本次移植一定开机」；开机仍取决于 `shennong_files` 资源与版本跨度。
* 换路线 / 换底包后必须重做基线：
  `python tools\ref_check.py emit <新成品包> --emit reference/<名字>.json`。

## v0.3.0 — 2026-11-10

* 主路线为 小米 18 Pro Max（`madrid`）→ 14 Pro；split_ab 布局、auto-fit 预算收敛、
  Gitee CI/发版脚本、合成数据回归测试。
