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

| 场景 | 入口 | 跑什么 |
| --- | --- | --- |
| Gitee Go（Linux runner） | `ci/gitee-go.yml` | `compileall` → `--selftest` → 离线单测 → `assets.py mirrors` → 源码包 |
| 本地 / 自建 Windows runner | `ci/run_pipeline.ps1` | 自检 → 拉资源 → 移植/精简/打包 → 7z 分卷 → 可选发布 |
| 历史 GitHub Actions | `.github/workflows/build.yml` | 同上，仅在 GitHub 侧生效 |

启用 Gitee Go：仓库 → 服务 → Gitee Go → 新建流水线 → 选「仓库内 YAML」→
把 `ci/gitee-go.yml` 拷成 `.workflow/build.yml`（插件参数字段以网页端步骤面板为准）。

**Gitee Go 跑不了 ROM 全流程**：runner 是 Linux、没有 40 GB 空闲盘，也没有
Windows 版 `lpmake / 7z / flashtools` 的落盘路径——这是设计上的分工，不是缺陷。

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
