<#
.SYNOPSIS
    一条命令把本仓库推到 Gitee（建仓 → 配远端 → 推送 → 校验）

.DESCRIPTION
    需要两样东西：Gitee 私人令牌 + 目标仓库路径。
    令牌只经环境变量/参数进入本次进程，不写进 .git/config（远端地址推完就还原成干净 URL）。

    Gitee 私人令牌：Gitee → 设置 → 私人令牌 → 生成新令牌，勾 `projects` 即可。
    首次推送会把整段历史（约 145 MiB）传上去，中断了重跑即可续传。

.PARAMETER Token
    Gitee 私人令牌；不给就读 $env:GITEE_TOKEN

.PARAMETER Owner
    目标账号/组织，默认 h-shennong

.PARAMETER Repo
    目标仓库名，默认 ShennongPort

.PARAMETER Public
    建公开仓库（默认私有；公开需要账号已实名认证）

.PARAMETER NoCreate
    仓库已经在网页上建好了，跳过 API 建仓

.EXAMPLE
    $env:GITEE_TOKEN = "xxxxxxxx"
    pwsh -File ci\push_to_gitee.ps1

.EXAMPLE
    # 公开仓库 + 顺手推所有分支与 tag
    pwsh -File ci\push_to_gitee.ps1 -Public -AllRefs
#>
[CmdletBinding()]
param(
    [string]$Token = $env:GITEE_TOKEN,
    [string]$Owner = 'h-shennong',
    [string]$Repo = 'shennong-port',
    [switch]$Public,
    [switch]$NoCreate,
    [switch]$AllRefs,
    # 有些 Windows 机器的 schannel TUF/证书链有问题，走 OpenSSL 后端更稳；异常时改回 schannel
    [ValidateSet('openssl', 'schannel')]
    [string]$SslBackend = 'openssl',

    # 没给令牌时从剪贴板取（在浏览器里生成令牌 -> 复制 -> 直接跑本脚本）
    [switch]$UseClipboard,

    # 推送成功后把令牌交给凭据管理器（GCM），之后 git push gitee 不再要令牌
    [switch]$NoRemember
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = 'utf-8'

function Step($name) { Write-Host ''; Write-Host ("=== {0}" -f $name) -ForegroundColor Cyan }

if (-not $Token -and $UseClipboard) {
    $clip = (Get-Clipboard -Raw -ErrorAction SilentlyContinue)
    if ($clip) { $clip = $clip.Trim() }
    if ($clip -match '^[A-Za-z0-9_\-]{20,64}$') {
        $Token = $clip
        Write-Host '  已从剪贴板取到令牌（不回显）' -ForegroundColor DarkGray
    } else {
        Write-Host '  [!] 剪贴板内容不像 Gitee 令牌（应为 20-64 位字母数字）' -ForegroundColor Yellow
    }
}
if (-not $Token) {
    throw '  [X] 缺少令牌：$env:GITEE_TOKEN = "xxxx" 或 -Token xxxx（Gitee → 设置 → 私人令牌）'
}
if (-not (Test-Path '.git')) { throw '  [X] 当前目录不是 git 仓库' }

$slug = "$Owner/$Repo"
$cleanUrl = "https://gitee.com/$slug.git"

# ---------------------------------------------------------------- 1. 建仓
Step "1. 目标仓库 $slug"
if (-not $NoCreate) {
    $repoArgs = @('tools\gitee_repo.py', '--token', $Token, '--owner', $Owner, '--repo', $Repo, 'ensure')
    if ($Public) { $repoArgs += '--public' }
    & python @repoArgs
    if ($LASTEXITCODE -ne 0) { throw '  [X] 建仓/查询失败（令牌权限、账号或仓库名冲突）' }
} else {
    Write-Host '  跳过建仓（-NoCreate）'
}

# ---------------------------------------------------------------- 2. 远端
Step '2. 远端配置'
$remotes = @(git remote)
if ($remotes -contains 'origin' -and $remotes -notcontains 'github') {
    git remote rename origin github
    Write-Host '  origin -> github（保留上游）'
}
if ($remotes -contains 'gitee') {
    git remote set-url gitee $cleanUrl
    Write-Host "  gitee 已存在，更新为 $cleanUrl"
} else {
    git remote add gitee $cleanUrl
    Write-Host "  新增 gitee -> $cleanUrl"
}
git remote -v | ForEach-Object { "    $_" } | Write-Host

# ---------------------------------------------------------------- 3. 推送
Step '3. 推送 main'
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
# 令牌只在这一条命令里出现，推完 .git/config 里仍是干净 URL
$pushUrl = "https://oauth2:$Token@gitee.com/$slug.git"
& git -c "http.sslBackend=$SslBackend" push $pushUrl "${branch}:${branch}" --progress
if ($LASTEXITCODE -ne 0) {
    throw '  [X] 推送失败：检查令牌是否勾了 projects、仓库是否为空仓、网络是否被拦'
}

if (-not $NoRemember) {
    # 存进 Windows 凭据管理器（GCM/DPAPI），以后 git push gitee 免令牌
    $credText = "protocol=https`r`nhost=gitee.com`r`nusername=oauth2`r`npassword=$Token`r`n`r`n"
    $credText | git credential approve
    if ($LASTEXITCODE -eq 0) {
        Write-Host '  令牌已交给凭据管理器，后续 git push gitee 免令牌（-NoRemember 可关闭）' -ForegroundColor DarkGray
    }
}

if ($AllRefs) {
    Step '4. 推送全部分支与 tag'
    & git -c "http.sslBackend=$SslBackend" push $pushUrl '--all' --progress
    if ($LASTEXITCODE -ne 0) { Write-Host '  [!] 分支推送有问题，继续推 tag' -ForegroundColor Yellow }
    & git -c "http.sslBackend=$SslBackend" push $pushUrl '--tags' --progress
}

# ---------------------------------------------------------------- 4. 校验
Step '5. 校验'
"  本地 $branch = $((git rev-parse --short $branch).Trim())"
# 只用 API 校验：私有仓库的 ls-remote 也要凭据，某些沙箱里 git 的子进程还会被拦
& python tools\gitee_repo.py --token $Token --owner $Owner --repo $Repo info
if ($LASTEXITCODE -ne 0) {
    Write-Host '  [!] API 校验没通过（令牌是否缺 projects 权限？），以网页为准' -ForegroundColor Yellow
}

Write-Host ''
Write-Host "  完成：https://gitee.com/$slug" -ForegroundColor Green
if ($Public) { Write-Host '  公开仓库可直接浏览；若显示待审核，去仓库设置里补实名信息' -ForegroundColor DarkGray }
