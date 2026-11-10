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
    目标仓库名，默认 XMAPort-SHALLOW

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
    [string]$Repo = 'XMAPort-SHALLOW',
    [switch]$Public,
    [switch]$NoCreate,
    [switch]$AllRefs,
    # 有些 Windows 机器的 schannel TUF/证书链有问题，走 OpenSSL 后端更稳；异常时改回 schannel
    [ValidateSet('openssl', 'schannel')]
    [string]$SslBackend = 'openssl'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = 'utf-8'

function Step($name) { Write-Host ''; Write-Host ("=== {0}" -f $name) -ForegroundColor Cyan }

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

if ($AllRefs) {
    Step '4. 推送全部分支与 tag'
    & git -c "http.sslBackend=$SslBackend" push $pushUrl '--all' --progress
    if ($LASTEXITCODE -ne 0) { Write-Host '  [!] 分支推送有问题，继续推 tag' -ForegroundColor Yellow }
    & git -c "http.sslBackend=$SslBackend" push $pushUrl '--tags' --progress
}

# ---------------------------------------------------------------- 4. 校验
Step '5. 校验'
$ref = & git -c "http.sslBackend=$SslBackend" ls-remote $cleanUrl "refs/heads/$branch" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host '  [!] ls-remote 需要凭据（私有仓库正常现象），以网页为准' -ForegroundColor Yellow
} else {
    "  远端 $branch = $ref"
}
"  本地 $branch = $(git rev-parse $branch)"

Write-Host ''
Write-Host "  完成：https://gitee.com/$slug" -ForegroundColor Green
Write-Host '  后续推送记得让凭据管理器记住：git config --global credential.helper manager' -ForegroundColor DarkGray
