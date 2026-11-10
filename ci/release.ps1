<#
.SYNOPSIS
    ShennongPort 手动发版台（GitHub Actions 的 workflow_dispatch / 手动 Run 的替代）

.DESCRIPTION
    Gitee 没有 Actions：没有 workflow_dispatch、没有 inputs、没有 secrets.GITHUB_TOKEN，
    也没有「Run workflow」那个带参数的面板。要「手动运行一次发版」，等价物就是这里：

      [1] 全流程 + 发版     自检 → 拉资源 → 移植/精简/打包 → 分卷 → 建 Release
      [2] 只打包 + 发版     工作区已有解包结果，跳过 1-5
      [3] 只自检             工具链 / 模块 / 配置 / 镜像链
      [4] 列出现有 Release   tag、附件、下载地址
      [5] 往已有 tag 补附件  不带参重跑时不重复建 Release
      [6] 只下载仓库归档     把 tag 的源码 zip 拉到 release\

    不交互时直接带参数跑（CI / 计划任务里用这个）：

      powershell -File ci\release.ps1 -Action full   -Publish
      powershell -File ci\release.ps1 -Action pack   -Publish -Tag sh-20261110
      powershell -File ci\release.ps1 -Action selftest
      powershell -File ci\release.ps1 -Action list
      powershell -File ci\release.ps1 -Action upload   -Tag sh-20261110 -Files release\*.7z.001

.EXAMPLE
    # 最常用：一条命令从零跑到 Release
    $env:GITEE_TOKEN = "xxxx"
    powershell -File ci\release.ps1
    # 然后按 1 回车
#>
[CmdletBinding()]
param(
    [ValidateSet('menu', 'full', 'pack', 'selftest', 'list', 'upload', 'archive')]
    [string]$Action = 'menu',

    [string]$Device = 'shennong',
    [ValidateSet('all', 'port', 'slim', 'pack', 'none')]
    [string]$Stage = 'all',
    [string]$Source = '',
    [string]$Target = '',
    [switch]$Offline,
    [switch]$NoSlim,

    [switch]$Publish,
    [string]$Tag = '',
    [int]$SplitMiB = 1900,
    [string[]]$Files = @(),

    [string]$Repo = $(if ($env:GITEE_REPO) { $env:GITEE_REPO } else { 'h-shennong/shennong-port' }),

    # 交互模式下不等待输入（自动化用）
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONIOENCODING = 'utf-8'

function Line($t) { Write-Host $t -ForegroundColor DarkGray }
function Head($t) {
    Write-Host ''
    Write-Host ("  === {0} ===" -f $t) -ForegroundColor Cyan
}
function Ask($text, $default) {
    if ($NoPrompt) { return $default }
    $v = Read-Host ("  {0} [{1}]" -f $text, $default)
    if ([string]::IsNullOrWhiteSpace($v)) { return $default }
    return $v.Trim()
}
function NeedToken {
    if (-not $env:GITEE_TOKEN) {
        Write-Host '  [!] 未设置 GITEE_TOKEN，发布类动作会失败。' -ForegroundColor Yellow
        Line '      Gitee → 设置 → 私人令牌（勾 projects）→ 复制 → $env:GITEE_TOKEN="xxx"'
        Line '      也可以先把令牌复制到剪贴板，再用 ci\push_to_gitee.ps1 -UseClipboard 推送；'
        Line '      发布用的令牌请在当前窗口设置一次环境变量。'
    }
}
function NewTag([string]$prefix) {
    if ($Tag) { return $Tag }
    return "{0}-{1}" -f $prefix, (Get-Date -Format 'yyyyMMdd-HHmm')
}

# ---------------------------------------------------------------- 动作：自检
function Do-Selftest {
    Head '自检'
    & python shennong_port.py --selftest
    if ($LASTEXITCODE -ne 0) { throw '自检未通过' }
    & python tools\assets.py mirrors
}

# ---------------------------------------------------------------- 动作：全流程/只打包
function Do-Pipeline([string]$mode) {
    $stageArg = if ($mode -eq 'pack') { 'pack' } else { $Stage }
    Head ("流程：" + $(if ($mode -eq 'pack') { '只打包（复用工作区）' } else { "stage=$stageArg" }))

    $pipeArgs = @('-Stage', $stageArg, '-Device', $Device)
    if ($Source) { $pipeArgs += @('-Source', $Source) }
    if ($Target) { $pipeArgs += @('-Target', $Target) }
    if ($Offline) { $pipeArgs += '-Offline' }
    if ($NoSlim) { $pipeArgs += '-NoSlim' }
    if ($SplitMiB -gt 0) { $pipeArgs += @('-SplitMiB', $SplitMiB) }
    if ($Publish) {
        NeedToken
        $pipeArgs += '-Publish'
        $pipeArgs += @('-Tag', (NewTag 'sh'))
    }

    & powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run_pipeline.ps1') @pipeArgs
    if ($LASTEXITCODE -ne 0) { throw "流水线失败（exit $LASTEXITCODE）" }
}

# ---------------------------------------------------------------- 动作：Release
function Do-List {
    Head "Release 列表（$Repo）"
    NeedToken
    if (-not $env:GITEE_TOKEN) { return }
    & python tools\gitee_release.py --repo $Repo list
}

function Do-Upload {
    Head "往已有 tag 补附件（$Repo）"
    NeedToken
    if (-not $env:GITEE_TOKEN) { return }
    $t = if ($Tag) { $Tag } else { Ask 'tag' ((Get-ChildItem release\*.7z.001 -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { $_.BaseName -replace '\.7z$', '' })) }
    if (-not $t) { throw '需要 -Tag' }
    $list = $Files
    if (-not $list -or $list.Count -eq 0) {
        $list = @(Get-ChildItem release\* -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne 'notes.md' } | ForEach-Object { $_.FullName })
    }
    if (-not $list -or $list.Count -eq 0) { throw 'release\ 下没有可上传的文件（先跑一次 -Action pack -Publish）' }
    & python tools\gitee_release.py --repo $Repo upload --tag $t @list
    Write-Host ''
    Write-Host ("  https://gitee.com/{0}/releases/tag/{1}" -f $Repo, $t) -ForegroundColor Green
}

function Do-Archive {
    Head '仓库归档'
    $t = if ($Tag) { $Tag } else { Ask 'tag' ((Get-Date -Format 'sh-yyyyMMdd')) }
    & python tools\gitee_release.py --repo $Repo archive --tag $t
}

# ---------------------------------------------------------------- 菜单
function Show-Menu {
    Write-Host ''
    Write-Host '  ShennongPort 发版台' -ForegroundColor White
    Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  [1] 全流程 + 发版    自检→拉资源→移植/精简/打包→分卷→Release'
    Write-Host '  [2] 只打包 + 发版    跳过 1-5，用现有工作区出 zip'
    Write-Host '  [3] 只自检           工具链/模块/配置/镜像链'
    Write-Host '  [4] 列出现有 Release tag 与附件'
    Write-Host '  [5] 往已有 tag 补附件'
    Write-Host '  [6] 下载仓库归档 zip'
    Write-Host '  [Q] 退出'
    Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ("  目标仓库: {0}   设备: {1}   分卷: {2} MiB" -f $Repo, $Device, $SplitMiB) -ForegroundColor DarkGray
    Write-Host ''
}

if ($Action -eq 'menu') {
    if ($NoPrompt) { throw '-Action menu 需要交互；自动化请用 -Action full|pack|selftest|list|upload|archive' }
    while ($true) {
        Show-Menu
        $choice = (Read-Host '  选择').Trim().ToLower()
        switch ($choice) {
            '1' {
                $Publish = $true
                do { $v = Ask '分卷 MiB（0=不分卷）' "$SplitMiB" } while (-not ($v -as [int]))
                $SplitMiB = [int]$v
                Do-Pipeline 'full'
            }
            '2' { $Publish = $true; Do-Pipeline 'pack' }
            '3' { Do-Selftest }
            '4' { Do-List }
            '5' { Do-Upload }
            '6' { Do-Archive }
            'q' { return }
            default { Write-Host '  无效选择' -ForegroundColor Yellow }
        }
    }
}

switch ($Action) {
    'selftest' { Do-Selftest }
    'full' { Do-Pipeline 'full' }
    'pack' { Do-Pipeline 'pack' }
    'list' { Do-List }
    'upload' { Do-Upload }
    'archive' { Do-Archive }
}
