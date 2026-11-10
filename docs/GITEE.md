# 从 GitHub 迁移到 Gitee：`long969697262/XMAPort-SHALLOW` → `h-shennong/XMAPort-SHALLOW`

先说结论：**代码不需要重写，改动集中在「运行期外链、CI、发布、仓库卫生」四处**，
功能与配置键全部向后兼容。下面的每一项都能在本仓库里找到对应文件。

---

## 1. 迁移基线

| 项 | 值 |
| --- | --- |
| 源 | GitHub `long969697262/XMAPort-SHALLOW`（前身仓库 `shennong_port`，私有） |
| 基线提交 | `902c935 修复bug`（本地完整历史，8 个提交，`main` 分支） |
| 目标 | Gitee `https://gitee.com/h-shennong/XMAPort-SHALLOW` |
| 跟踪文件 | 149 个，工作区约 300 MiB，`.git` 约 145 MiB |
| 最大单文件 | `assets/root_images/recovery_twrp.img.zst` = 61,231,719 B（≈ 58 MiB）→ 低于 Gitee 单文件 100 MiB 硬上限 |
| 主代码许可 | MIT（`LICENSE`），第三方工具各自原许可 |

> 迁移时 GitHub 仓库处于私有状态，无法用匿名通道抓取；本仓库内容取自
> 源仓库的完整本地克隆（同 `902c935`），历史与提交信息原样保留。

---

## 2. 为什么要改：Gitee 与 GitHub 的四个硬差异

| 差异 | 在 GitHub 上的做法 | 在 Gitee 上的结果 | 本次处理 |
| --- | --- | --- | --- |
| CI | `.github/workflows/build.yml` | Gitee 不解析 `.github/`，等于没有 CI | 新增 `ci/gitee-go.yml` + `ci/run_pipeline.ps1`，原 workflow 保留给 GitHub 侧 |
| 发布 | `gh release create`（GitHub CLI） | Gitee 没有 `gh`，也不认 `GITHUB_TOKEN` | 新增 `tools/gitee_release.py`（Gitee OpenAPI v5，`GITEE_TOKEN`） |
| 运行期下载 | `raw.githubusercontent.com` 单点直连 | 国内经常连不上或极慢，`--selftest` 全 OK 也会卡在拉资源 | `tools/assets.py` 改为**镜像链**：Gitee 镜像 → 加速前缀 → GitHub raw，逐个回落 |
| 仓库卫生 | `.gitattributes` 只有 `* text=auto` | 中文 Windows 脚本/文档混用 CRLF，易被网页编辑器整文件改写 | 重写 `.gitattributes`：文本按 LF 入库、`bat/cmd/ps1/ini/txt` 按 CRLF 检出、二进制全部 `binary` |

顺带对齐的还有：仓库名（`ShennongPort` → `XMAPort-SHALLOW`）、README 的克隆地址与徽章、
`assets/README.md` 的镜像说明、`.gitignore` 的 `release/` 与 `*.7z.*`。

---

## 3. 改动清单（diff 视角）

| 文件 | 改动 | 影响 |
| --- | --- | --- |
| `tools/assets.py` | 重写下载层：`base_urls()` 生成镜像链、`_fetch_one()` 单源重试+断点续传、`fetch_icons()` 给「完美图标」用 | 13 个 `shennong_files` 资源自动多源回落；`asset_base` 语义从「唯一源」变为「链首（仍可回落）」 |
| `tools/assets.py` | 新增子命令 `mirrors [--probe]` | 一条命令看清哪条镜像通 |
| `tools/shennong_patch.py` | `step_icons()` 不再写死 `codeload.github.com`，改调 `asset_mod.fetch_icons()`，失败信息带上配置项 | 图标步骤在国内可用；失败可读 |
| `tools/gitee_release.py` | **新增**：`list / create / upload / archive`，纯标准库 multipart | 替代 `gh release create`，产物直接进 Gitee Release 附件 |
| `tools/gitee_repo.py` | **新增**：`info / create / ensure`，走 Gitee OpenAPI 建仓 | 令牌一给就能一条命令建仓库 |
| `ci/push_to_gitee.ps1` | **新增**：建仓 → 配远端 → 推送 → 校验 | 迁移落地的一条命令（令牌只进进程，不写 `.git/config`） |
| `ci/run_pipeline.ps1` | **新增**：自检 → 拉资源 → 移植/精简/打包 → 7z 分卷 → 可选发布 | 本地 / 自建 Windows runner 一条命令跑完原 workflow |
| `ci/gitee-go.yml` | **新增**：Gitee Go 模板（语法编译 + `--selftest` + 离线单测 + 源码包） | Gitee 侧最小可用 CI；插件参数字段以 Gitee Go 网页端为准 |
| `config.ini` | `[shennong]` 增 `asset_mirrors=`、`icons_url=`，注释重写 | 旧配置继续有效（空值 = 用内置镜像链） |
| `XMAPort.py` | 自检与标题改名；自检多打印一行 `asset mirrors = ...` | 一眼看出当前镜像顺序 |
| `README.md` | Gitee 徽章 / 克隆地址 / §3.3 镜像链 / §5「在 Gitee 上跑」/ 目录树 | 新用户按 Gitee 地址就能走通 |
| `.gitattributes` | 按类别声明 eol 与 binary（见上表） | 首次提交会有一次换行归一化（不影响运行） |
| `.gitignore` | 加 `release/`、`*.7z`、`*.7z.*`、`*.part`、`*.log`、`__pycache__` | 分卷与日志不会误入库 |
| `docs/GITEE.md` | **新增**（本文件） | 迁移说明 + 建仓/推送/发布/回滚步骤 |

**没有动的**：`tools/make_hyper.py`、`pack_partitions.py`、`extract_img.py`、`slim.py`、
`package_zip.py`、`stage_common.py`、`device_profiles.py`、`tests/*`、`assets/*`、
`.github/workflows/build.yml`。上游移植逻辑一行没改。

---

## 4. 建仓 + 推代码（在你自己机器上执行）

### 4.1 建仓库

Gitee 网页 → 右上角 `+` → 新建仓库：

* 仓库名：`XMAPort-SHALLOW`
* 路径：`h-shennong/XMAPort-SHALLOW`
* **不要**勾选「使用 README 初始化仓库」「添加 .gitignore」「添加开源许可证」，否则要先合并历史
* 公开仓库需要账号完成实名认证；只想自己用就选私有

### 4.2 推送（本地已有本目录，历史完整）

一键版（建仓 + 配远端 + 推送 + 校验，只需令牌）：

```powershell
$env:GITEE_TOKEN = "你的 Gitee 私人令牌"
pwsh -File ci\push_to_gitee.ps1            # 私有仓库
pwsh -File ci\push_to_gitee.ps1 -Public    # 公开仓库（需实名认证）
```

手工版：

```bash
cd XMAPort-SHALLOW
git remote rename origin github
git remote add gitee https://gitee.com/h-shennong/XMAPort-SHALLOW.git
git push -u gitee main
git push gitee --tags
```

首次推送约 145 MiB（`.git`），国内直连 Gitee 通常几分钟内完成。
若中途被掐断，直接重跑 `git push -u gitee main`，git 会续传已上传的对象。

> 本机（Windows）如果出现 `schannel: AcquireCredentialsHandle failed … SEC_E_NO_CREDENTIALS`，
> 是系统 TLS 后端的问题，不是仓库问题：`git config --global http.sslBackend openssl` 即可，
> `ci/push_to_gitee.ps1` 默认就带 `-c http.sslBackend=openssl`。

### 4.3 可选：把 GitHub 留作上游

```bash
git remote set-url --push github DISABLED   # 防止误推回 GitHub
git fetch github main                       # 需要你本机已登录的凭据
```

---

## 5. 让「镜像链」第 1 条真正生效（强烈建议）

`tools/assets.py` 的链首是 `https://gitee.com/h-shennong/14PRO_SHALLOW_ROM/raw/main/shennong_files/`，
但那个仓库目前还不存在，所以实际会落到 `ghfast.top`。补上它：

1. Gitee → 新建仓库 → **导入已有仓库** → 填 `https://github.com/XHR222/14PRO_SHALLOW_ROM`
2. 仓库路径填 `h-shennong/14PRO_SHALLOW_ROM`（脚本按这个路径拼 URL）
3. 创建后访问一次 `https://gitee.com/h-shennong/14PRO_SHALLOW_ROM/raw/main/shennong_files/fstab.qcom`
   确认能下（11,535 B）
4. 验证：

```bat
python tools\assets.py mirrors --probe
python tools\assets.py fetch fstab.qcom
```

> 只想钉一条源、不要回落：`config.ini` 里写 `asset_base=...`，再把它之外的镜像
> 从 `asset_mirrors` 里删掉即可（内置链永远在末尾，属于兜底）。

同一个思路可以给「完美图标」用：导入 `pzcn/Perfect-Icons-Completion-Project`，
路径写成 `h-shennong/Perfect-Icons-Completion-Project`，或在 `config.ini` 里
`icons_url=` 直接指定 zip 地址。

---

## 6. CI 与发布

### 6.1 Gitee Go（Linux runner，轻量）

仓库 → 服务 → Gitee Go → 新建流水线 → 选「仓库内 YAML」→ 把 `ci/gitee-go.yml`
内容放到 `.workflow/build.yml`（或按网页端步骤面板把 `commands` 粘进去）。

跑的是：`compileall` → `XMAPort.py --selftest` → `tests/test_stages.py` →
`tests/test_payload_args.py` → `tools/assets.py mirrors` → 打 `XMAPort-SHALLOW-src.zip`。

**它跑不了 ROM 全流程**：Gitee Go 的 runner 是 Linux、没有 40 GB 空闲盘，也没有
Windows 版 `lpmake/7z/flashtools` 的落盘路径。ROM 流水线请用下面这条。

### 6.2 Windows 全流程（本地 / 自建 runner）

```powershell
pwsh -File ci\run_pipeline.ps1 -Stage all
pwsh -File ci\run_pipeline.ps1 -Stage pack -Publish -Tag sh-20261110
```

脚本会复刻原 workflow 的全部步骤（自检、拉资源、三阶段、7z 分卷 1900 MiB、
上传附件），只是把 `gh` 换成了 Gitee API。

### 6.3 发布令牌

Gitee → 设置 → 私人令牌 → 生成，权限勾 `projects` 即可：

```bat
set GITEE_TOKEN=xxxxxxxxxxxxxxxx
python tools\gitee_release.py create --tag sh-20261110 --title "XMAPort-SHALLOW 20261110" ^
    --notes "移植→精简→打包自动产物" release\*.7z.001 workspace\output\*.zip
```

单附件超过约 90 MiB 会提示，用 `7z -v1900m` 分卷后逐个上传（`ci/run_pipeline.ps1 -SplitMiB 1900` 已内置）。

---

## 7. 体积与配额

* 本仓库最大单文件 58 MiB、`.git` 约 145 MiB，免费额度内很宽裕，**不需要 Git LFS**。
* 以后再往里放 `super.img`/整包 ROM 时会撞 100 MiB 单文件上限：那种大文件走
  Release 附件或 `7z -v` 分卷，不要提交进仓库。
* `assets/shennong_files/`（310 MiB 资源）与 `workspace/` 已在 `.gitignore` 里，永远不会入库。

---

## 8. 回滚

```bash
git reset --hard 902c935          # 回到迁移前
git remote rename gitee origin    # 恢复远端命名
```

迁移只碰了上表那些文件，回滚不会丢上游代码。

---

## 9. 已知差异 / 待办

* Gitee Go 的 YAML 字段随版本有差异（`step: build@python` 的参数名以网页端步骤面板为准）；
  本仓库的真正契约是 `ci/run_pipeline.ps1` 里的命令序列，插件不匹配时照抄即可。
* GitHub 侧仓库是私有的，迁移基线是本地克隆的 `902c935`；如果 GitHub 上还有更新的提交，
  先 `git fetch github main && git merge github/main` 再推 Gitee。
* Gitee 的 Release 附件与 GitHub Release 不互通：历史 Release 需要按需重传
  （`python tools/gitee_release.py upload`）。
