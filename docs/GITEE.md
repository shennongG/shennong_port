# Gitee 部署、CI 与发布

本仓库托管在 `https://gitee.com/h-shennong/shennong-port`。
这份文档写清楚：怎么建仓推送、怎么让资源链首那条镜像生效、CI 怎么跑、
产物怎么发到 Release，以及体积/配额上的硬限制。

---

## 1. 建仓与推送

### 1.1 网页建仓

Gitee 右上角 `+` → 新建仓库：

* 仓库名：`shennong-port`
* **不要**勾「使用 README 初始化」「添加 .gitignore」「添加开源许可证」，否则要先合并历史
* 公开仓库需要账号完成实名认证；只想自己用就选私有

### 1.2 一条命令（推荐）

```powershell
$env:GITEE_TOKEN = "你的 Gitee 私人令牌"     # 权限勾 projects 即可
powershell -File ci\push_to_gitee.ps1 -UseClipboard
```

脚本做的事：API 建空仓 → 配 `gitee` 远端（原 `origin` 保留为上游）→ 推送当前分支 →
把令牌交给 Windows 凭据管理器（`-NoRemember` 可关闭）→ `tools/gitee_repo.py info`
校验远端 head。

令牌也可以从剪贴板读（`-UseClipboard`），不落命令行历史；不想把令牌交给脚本时，
手工两步：

```bash
git remote add gitee https://gitee.com/h-shennong/shennong-port.git
git push -u gitee main
```

首次推送约 145 MiB（`.git`）。中断了就重跑，git 会续传已完成的对象。

> 本机若报 `schannel: AcquireCredentialsHandle failed … SEC_E_NO_CREDENTIALS`，
> 是系统 TLS 后端问题：`git config --global http.sslBackend openssl` 即可；
> `ci/*.ps1` 默认就带这个参数。

---

## 2. 让镜像链第 1 条生效（建议做）

`tools/assets.py` 的链首是 `https://gitee.com/h-shennong/rom-assets/raw/main/shennong_files/`，
仓库不存在时实际会落到公益加速。补上它：

1. Gitee → 新建仓库 → **导入已有仓库** → 填资源仓库地址
2. 仓库路径填 `h-shennong/rom-assets`（脚本按这个路径拼 URL）
3. 创建后访问一次 `https://gitee.com/h-shennong/rom-assets/raw/main/shennong_files/fstab.qcom`
   确认能下（11,535 B）
4. 验证：

```bat
python tools\assets.py mirrors --probe
python tools\assets.py fetch fstab.qcom
```

图标包同理：先把图标工程导入成 Gitee 仓库（默认期望 `h-shennong/icons-pack-project`），
或在 `config.ini` 里用 `icons_url=` 直接指定 zip 地址。

> 资源的版权与许可证见 [../NOTICE.md](../NOTICE.md) 第 2 节：本仓库只提供下载脚本，
> 不随包分发这些文件。

---

## 3. CI

### 3.1 为什么这里不像 GitHub Actions

Gitee 没有 Actions 这套东西，`Gitee Go` 是另一个产品，差异是结构性的：

| GitHub Actions | Gitee 侧 | 后果 |
| --- | --- | --- |
| `.github/workflows/*.yml` 自动生效 | 只认 `.workflow/*.yml`，还要在网页「服务 → Gitee Go」里开通并绑定 | 目录得另放一份，不能指着 `.github/` |
| `on: workflow_dispatch` + `inputs` | **没有**等价物；只有网页上的「运行」按钮 | 「带参数手动跑」要靠脚本，不是点面板 |
| `secrets.GITHUB_TOKEN` 自动注入 | 没有内置令牌；要自己建私人令牌，塞进流水线环境变量 | 发布这一步得显式给 `GITEE_TOKEN` |
| `actions/checkout`、`actions/cache` 等 marketplace | 只有平台内置的一批步骤插件，字段名随版本变 | 缓存/分卷这类事自己写脚本更稳 |
| Runner 可选 `windows-latest` | Gitee Go 的 runner 是 Linux | `lpmake/7z/flashtools` 这套 Windows 工具链跑不了 |
| `gh release create` | 没有 `gh`；用 OpenAPI（本仓库 `tools/gitee_release.py`） | 发布改成脚本调用 |

所以本仓库的分工是：**能上 Gitee Go 的只有轻量校验，真正的出包与发版在 Windows 上手动/脚本跑**。
这不是退步，是把「Actions 能做的事」换成了「一条命令 + 参数」，反而更好控制。

### 3.2 手动运行（等价于 Actions 的 Run workflow）

```powershell
cd F:\DeepSeek\XMAPort-SHALLOW
powershell -File ci\release.ps1          # 打开菜单，按 1 就全流程 + 发版
```

菜单项：

```
[1] 全流程 + 发版    自检 → 拉资源 → 移植/精简/打包 → 分卷 → 建 Release
[2] 只打包 + 发版    用现有工作区出 zip（跳过 1-5）
[3] 只自检           工具链/模块/配置/镜像链
[4] 列出现有 Release tag 与附件
[5] 往已有 tag 补附件
[6] 下载仓库归档 zip
```

不想交互、要写进计划任务或别的 CI，就直接带参数：

```powershell
$env:GITEE_TOKEN = "xxxx"                        # 只有发布类动作需要
powershell -File ci\release.ps1 -Action full -Publish
powershell -File ci\release.ps1 -Action pack -Publish -Tag sh-20261110
powershell -File ci\release.ps1 -Action selftest
powershell -File ci\release.ps1 -Action list
powershell -File ci\release.ps1 -Action upload -Tag sh-20261110 -Files release\*.7z.001
```

等价于 GitHub 上那套 `Run workflow` + 三个 inputs（`device / stage / offline`），
只是参数从网页面板换成了命令行。

### 3.3 三种入口的分工

| 场景 | 入口 | 跑什么 |
| --- | --- | --- |
| 手动发一版 | `ci/release.ps1` | 菜单 / 参数，一路到 Release |
| 只要产物不要发布 | `ci/run_pipeline.ps1 -Stage all` | 自检 → 拉资源 → 三阶段 → 分卷，产物留 `release\` |
| Gitee Go（Linux runner） | `ci/gitee-go.yml` | `compileall` → `--selftest` → 离线单测 → `assets.py mirrors` → 源码包 |
| 历史 GitHub Actions | `.github/workflows/build.yml` | 同上，仅在 GitHub 侧生效 |

启用 Gitee Go：仓库 → 服务 → Gitee Go → 新建流水线 → 选「仓库内 YAML」→
把 `ci/gitee-go.yml` 拷成 `.workflow/build.yml`（插件参数字段以网页端步骤面板为准）。
这条流水线**只做校验**，别指望它出 7.75 GiB 的 super。


```powershell
powershell -File ci\run_pipeline.ps1 -Stage all
powershell -File ci\run_pipeline.ps1 -Stage pack -Publish -Tag sh-20261110
```

---

## 4. 发布到 Release

```bat
set GITEE_TOKEN=xxxxxxxxxxxxxxxx
python tools\gitee_release.py list
python tools\gitee_release.py create --tag sh-20261110 --title "ShennongPort 20261110" ^
    --notes-file release\notes.md release\*.7z.001 workspace\output\*.zip
```

* 单附件超过约 90 MiB 会提示，用 `7z -v1900m` 分卷后逐个上传；
* `ci/run_pipeline.ps1 -Publish` 已内置「分卷 + 建 Release + 上传附件」；
* 上传后的附件地址在 `list` 里能看到。

---

## 5. 体积与配额

* 目前最大单文件约 58 MiB（`assets/root_images/recovery_twrp.img.zst`），`.git`
  约 145 MiB，**不需要 Git LFS**；
* 单文件 100 MiB 是硬上限：整包 ROM、`super.img` 这类大文件走 Release 附件或分卷，
  不进版本库；
* `assets/shennong_files/`（约 310 MiB）与 `workspace/` 已在 `.gitignore` 里。

---

## 6. 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `ParserError` 指向中文行 | 脚本被存成无 BOM 的 UTF-8，PowerShell 5.1 按 GBK 解析 | 保持 UTF-8 with BOM；本仓库脚本已带 BOM |
| `Authentication failed` | 令牌没勾 `projects`，或用了过期的令牌 | 重新生成令牌，`git config --unset credential.helper` 后重试 |
| `git push` 一直要密码 | 凭据管理器没存住 | 跑一次 `ci\push_to_gitee.ps1 -UseClipboard` |
| 资源下载全失败 | 镜像都被墙/限速 | `assets.py mirrors --probe` 挑一条可用的，写进 `config.ini` |
| Gitee 提示文件超 50 MB | 只是提示，不影响推送 | 保持单文件 < 100 MiB 即可 |
