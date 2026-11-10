<#
.SYNOPSIS
    XMAPort-SHALLOW 构建流水线（Gitee 版：本地 / 自建 Windows runner / Gitee Go 都能直接跑）

.DESCRIPTION
    一条命令跑完 GitHub Actions 里那条 workflow 的全部内容：
    自检 → 拉资源（镜像链）→ 移植/精简/打包 → 分卷 → 可选发布到 Gitee Release。

    与 .github/workflows/build.yml 的区别：
      * 资源下载走 tools/assets.py 的镜像链（Gitee 镜像 → 加速前缀 → GitHub raw），
        不再依赖 gitlfs / gh / actions/cache；
      * 发布用 Gitee OpenAPI（tools/gitee_release.py），只需要 GITEE_TOKEN；
      * 所有中间产物都落在仓库目录内，跑完可直接删。

.EXAMPLE
    # 只自检
    .\ci\run_pipeline.ps1 -SelftestOnly

    # 全流程（先拉 310 MiB 资源）
    .\ci\run_pipeline.ps1 -Stage all

    # 有工作区了，只打包
    .\ci\run_pipeline.ps1 -Stage pack

    # 跑完并发布到 Gitee Release
    $env:GITEE_TOKEN = "xxxx"
    .\ci\run_pipeline.ps1 -Stage all -Publish

.EXAMPLE
    # CI 里用环境变量驱动（Gitee Go / 自建 runner 通用）
    $env:STAGE='all'; $env:DEVICE='shennong'; $env:OFFLINE='false'
    .\ci\run_pipeline.ps1
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'port', 'slim', 'pack', 'none')]
    [string]$Stage = $(if ($env:STAGE) { $env:STAGE } else { 'all' }),

    [string]$Device = $(if ($env:DEVICE) { $env:DEVICE } else { 'shennong' }),

    [string]$Source = $(if ($env:SOURCE_URL) { $env:SOURCE_URL } else { '' }),
    [string]$Target = $(if ($env:TARGET_URL) { $env:TARGET_URL } else { '' }),

    [switch]$Offline,
    [switch]$NoSlim,
    [switch]$SelftestOnly,

    # 分卷（MiB），0 = 不分卷
    [int]$SplitMiB = 1900,

    # 发布到 Gitee Release（需要 GITEE_TOKEN）
    [switch]$Publish,
    [string]$Tag = '',
    [string]$Repo = $(if ($env:GITEE_REPO) { $env:GITEE_REPO } else { 'h-shennong/XMAPort-SHALLOW' }),

    # 跳过分卷/发布，只留 workspace/output 里的 zip
    [switch]$NoPackage
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONIOENCODING = 'utf-8'
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw '  [X] 找不到 python，请先装 Python 3.8+（建议 3.12）' }

function Step($name) {
    Write-Host ''
    Write-Host ("=== {0}" -f $name) -ForegroundColor Cyan
}

function Invoke-Py {
    param([string[]]$PyArgs)
    Write-Host ("  $ python {0}" -f ($PyArgs -join ' ')) -ForegroundColor DarkGray
    & python @PyArgs
    if ($LASTEXITCODE -ne 0) { throw ("python {0} 退出码 {1}" -f ($PyArgs -join ' '), $LASTEXITCODE) }
}

function Show-Disk {
    Get-PSDrive -PSProvider FileSystem |
        Where-Object { $_.Name -in @('C', 'D', 'E', 'F') } |
        ForEach-Object { "  {0}: 剩余 {1:N1} GiB" -f $_.Name, ($_.Free / 1GB) } |
        Write-Host
}

# ---------------------------------------------------------------- 0. 环境
Step '0. 环境'
"  python  : $(& python --version 2>&1)"
"  仓库    : $Root"
"  阶段    : $Stage / 设备 $Device / offline=$($Offline.IsPresent)"
Show-Disk

# ---------------------------------------------------------------- 1. 自检
Step '1. 自检（工具链 / 模块 / 配置）'
Invoke-Py @('XMAPort.py', '--selftest')
if ($SelftestOnly) { Write-Host '  只自检，结束' -ForegroundColor Green; return }

# ---------------------------------------------------------------- 2. 资源
if ($Stage -in @('all', 'slim', 'pack') -and -not $Offline) {
    Step '2. 拉取 14 Pro 资源（镜像链，约 310 MiB，已缓存则秒过）'
    Invoke-Py @('tools/assets.py', 'fetch')
} else {
    Step '2. 跳过资源下载'
    Write-Host "  offline=$($Offline.IsPresent) stage=$Stage"
}

# ---------------------------------------------------------------- 3. 主流程
Step "3. 主流程（stage=$Stage）"
$a = @('XMAPort.py', '--auto', '--device', $Device, '--stage', $Stage)
if ($Offline) { $a += '--offline' }
if ($NoSlim) { $a += '--no-slim' }
if ($Source) { $a += @('--source', $Source) }
if ($Target) { $a += @('--target', $Target) }
Invoke-Py $a

# ---------------------------------------------------------------- 4. 产物
Step '4. 产物'
foreach ($d in @('workspace\output', 'workspace\packed')) {
    $p = Join-Path $Root $d
    if (Test-Path $p) {
        Get-ChildItem $p -File | ForEach-Object { "  {0,-60} {1,10:N1} MiB" -f $_.Name, ($_.Length / 1MB) } | Write-Host
    }
}

if ($NoPackage -or $Stage -in @('port', 'slim', 'none')) {
    Write-Host '  未进入打包阶段，跳过分卷/发布' -ForegroundColor Yellow
    return
}

$zip = Get-ChildItem 'workspace\output\*.zip' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $zip) { throw '  [X] 没有产出卡刷包 zip' }

$releaseDir = Join-Path $Root 'release'
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
$volumes = @()
if ($SplitMiB -gt 0) {
    Step "5. 分卷（$SplitMiB MiB/卷，7z -mx=0 只切不压）"
    Remove-Item (Join-Path $releaseDir '*.7z*') -ErrorAction SilentlyContinue
    & .\tools\7z.exe a -mx=0 "-v${SplitMiB}m" (Join-Path $releaseDir "$($zip.BaseName).7z") $zip.FullName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '7z 分卷失败' }
    $volumes = @(Get-ChildItem (Join-Path $releaseDir '*.7z.*') | Sort-Object Name)
    $volumes | ForEach-Object { "  {0,-60} {1,10:N1} MiB" -f $_.Name, ($_.Length / 1MB) } | Write-Host
    Copy-Item $zip.FullName $releaseDir -Force
} else {
    Copy-Item $zip.FullName $releaseDir -Force
}

# ---------------------------------------------------------------- 6. 发布
if (-not $Publish) {
    Write-Host ''
    Write-Host '  未指定 -Publish，产物留在 release\ 目录' -ForegroundColor Yellow
    Write-Host '  手动发布：' -ForegroundColor DarkGray
    Write-Host ('    $env:GITEE_TOKEN="xxx"; python tools/gitee_release.py create --tag {0} --title "{0}" release\*' -f `
        ($(if ($Tag) { $Tag } else { 'sh-' + (Get-Date -Format 'yyyyMMdd-HHmm') }))) -ForegroundColor DarkGray
    return
}

Step '6. 发布到 Gitee Release'
if (-not $env:GITEE_TOKEN) { throw '  [X] -Publish 需要 GITEE_TOKEN（Gitee → 设置 → 私人令牌）' }
if (-not $Tag) { $Tag = 'sh-' + (Get-Date -Format 'yyyyMMdd-HHmm') }
$notes = @"
移植 → 精简 → 打包 自动产物。

- 目标设备: $Device
- 阶段: $Stage
- 源包: $(if ($Source) { $Source } else { 'config.ini' })
- 底包: $(if ($Target) { $Target } else { 'config.ini' })
- 卡刷包: $($zip.Name)

合并分卷：``7z x *.7z.001`` 或 ``cat *.7z.* > all.7z && 7z x all.7z``。
"@
$notesFile = Join-Path $releaseDir 'notes.md'
$notes | Out-File $notesFile -Encoding utf8

$files = @(Get-ChildItem $releaseDir -File | Where-Object { $_.Name -ne 'notes.md' } | ForEach-Object { $_.FullName })
$files += @(Get-ChildItem 'workspace\*.log' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })

Invoke-Py (@('tools/gitee_release.py', '--repo', $Repo, 'create', '--tag', $Tag,
               '--title', ("XMAPort-SHALLOW {0}" -f (Get-Date -Format 'yyyyMMdd')),
               '--notes-file', $notesFile) + $files)

Write-Host ''
Write-Host "  完成：https://gitee.com/$Repo/releases/tag/$Tag" -ForegroundColor Green
