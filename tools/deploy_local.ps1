param(
    [ValidateSet("deploy", "start", "stop", "status")]
    [string]$Action = "deploy",
    [string]$Branch = "feat/account-profile-avatar",
    [switch]$NoPull,
    [switch]$NoInstall,
    [switch]$SkipTests,
    [switch]$WithDesktop
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root ".local-run"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$DashboardPid = Join-Path $RunDir "dashboard.pid"
$SignalingPid = Join-Path $RunDir "signaling.pid"
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Native([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Perintah gagal ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

function New-Secret {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Ensure-EnvValue([string]$Key, [string]$Value) {
    $envPath = Join-Path $Root ".env"
    $text = Get-Content $envPath -Raw
    $pattern = "(?m)^" + [Regex]::Escape($Key) + "=\s*$"
    if ($text -match $pattern) {
        $text = [Regex]::Replace($text, $pattern, "$Key=$Value")
        Set-Content -Path $envPath -Value $text -Encoding UTF8
    } elseif ($text -notmatch ("(?m)^" + [Regex]::Escape($Key) + "=")) {
        Add-Content -Path $envPath -Value "`n$Key=$Value" -Encoding UTF8
    }
}

function Initialize-Env {
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        Copy-Item (Join-Path $Root ".env.example") $envPath
        Write-Host "Membuat .env dari .env.example."
    }
    Ensure-EnvValue "WEBWATCH_SESSION_SECRET" (New-Secret)
    Ensure-EnvValue "WEBRTC_SECRET_KEY" (New-Secret)
    Ensure-EnvValue "WEBRTC_ADMIN_TOKEN" (New-Secret)
    Ensure-EnvValue "WEBWATCH_MAIL_BACKEND" "console"
}

function Import-DotEnv {
    $envPath = Join-Path $Root ".env"
    foreach ($line in Get-Content $envPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$key" -Value $value
    }
}

function Get-ManagedProcess([string]$PidFile) {
    if (-not (Test-Path $PidFile)) { return $null }
    $savedPid = (Get-Content $PidFile -Raw).Trim()
    if (-not $savedPid) { return $null }
    return Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
}

function Stop-LocalServices {
    Write-Step "Menghentikan service lokal"
    foreach ($item in @(
        @{ Name = "dashboard"; File = $DashboardPid },
        @{ Name = "signaling"; File = $SignalingPid }
    )) {
        $process = Get-ManagedProcess $item.File
        if ($null -ne $process) {
            Stop-Process -Id $process.Id -Force
            Write-Host "Stopped $($item.Name) (PID $($process.Id))."
        }
        Remove-Item $item.File -Force -ErrorAction SilentlyContinue
    }
}

function Wait-Url([string]$Name, [string]$Url, [int]$Retries = 30) {
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Name siap: $Url" -ForegroundColor Green
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "$Name tidak siap. Periksa log di $RunDir"
}

function Start-LocalServices {
    Initialize-Env
    Import-DotEnv
    New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

    if (-not (Test-Path $VenvPython)) {
        throw "Virtual environment belum tersedia. Jalankan: .\tools\deploy_local.ps1 deploy"
    }
    if ($null -ne (Get-ManagedProcess $DashboardPid) -or $null -ne (Get-ManagedProcess $SignalingPid)) {
        throw "Service lokal masih berjalan. Jalankan action stop terlebih dahulu."
    }

    Write-Step "Menjalankan WebRTC signaling"
    $signal = Start-Process -FilePath $VenvPython -ArgumentList @("WebRTC_Meet/app.py") `
        -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $RunDir "signaling.out.log") `
        -RedirectStandardError (Join-Path $RunDir "signaling.err.log") -PassThru -WindowStyle Hidden
    Set-Content $SignalingPid $signal.Id

    $entryPoint = if ($WithDesktop) { "main.py" } else { "app.py" }
    Write-Step "Menjalankan dashboard melalui $entryPoint"
    $dashboard = Start-Process -FilePath $VenvPython -ArgumentList @($entryPoint) `
        -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $RunDir "dashboard.out.log") `
        -RedirectStandardError (Join-Path $RunDir "dashboard.err.log") -PassThru
    Set-Content $DashboardPid $dashboard.Id

    Wait-Url "Signaling" "http://localhost:5001/healthz"
    Wait-Url "Dashboard" "http://localhost:5000/auth/login" 60
    Write-Host "`nWeWatch berjalan:" -ForegroundColor Green
    Write-Host "  Dashboard : http://localhost:5000"
    Write-Host "  Meeting   : http://localhost:5001"
    Write-Host "  Log       : $RunDir"
}

function Show-LocalStatus {
    Write-Step "Status service lokal"
    foreach ($item in @(
        @{ Name = "Dashboard"; File = $DashboardPid; Url = "http://localhost:5000/auth/login" },
        @{ Name = "Signaling"; File = $SignalingPid; Url = "http://localhost:5001/healthz" }
    )) {
        $process = Get-ManagedProcess $item.File
        if ($null -ne $process) {
            Write-Host "$($item.Name): RUNNING (PID $($process.Id)) — $($item.Url)" -ForegroundColor Green
        } else {
            Write-Host "$($item.Name): STOPPED" -ForegroundColor Yellow
        }
    }
}

function Deploy-Local {
    Stop-LocalServices

    if (-not $NoPull) {
        Write-Step "Memeriksa repository"
        $dirty = git status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "Folder ini bukan repository Git yang valid." }
        if ($dirty) {
            throw "Ada perubahan lokal yang belum disimpan. Commit atau stash sebelum deploy.`n$dirty"
        }
        Invoke-Native "git" @("fetch", "origin", $Branch)
        Invoke-Native "git" @("switch", $Branch)
        Invoke-Native "git" @("pull", "--ff-only", "origin", $Branch)
    }

    Write-Step "Menyiapkan virtual environment"
    if (-not (Test-Path $VenvPython)) {
        Invoke-Native "python" @("-m", "venv", ".venv")
    }
    if (-not $NoInstall) {
        Invoke-Native $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-Native $VenvPython @("-m", "pip", "install", "-r", "requirements.txt")
    }

    Initialize-Env
    Import-DotEnv

    if (-not $SkipTests) {
        Write-Step "Menjalankan release checks"
        Invoke-Native $VenvPython @("-m", "unittest", "discover", "-s", "tests", "-v")
        Invoke-Native $VenvPython @("-m", "compileall", "-q", ".")
        Invoke-Native $VenvPython @("tools/check_template_js.py")
        Invoke-Native $VenvPython @("tools/check_ui_contracts.py")
        Invoke-Native "git" @("diff", "--check")
    }

    Start-LocalServices
}

try {
    switch ($Action) {
        "deploy" { Deploy-Local }
        "start"  { Start-LocalServices }
        "stop"   { Stop-LocalServices }
        "status" { Show-LocalStatus }
    }
} catch {
    Write-Host "`nDEPLOY GAGAL: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Periksa log di $RunDir jika proses sempat dijalankan."
    exit 1
}
