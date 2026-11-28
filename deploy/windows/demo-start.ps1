# Демо Satti на iPhone через Expo Go — одной командой (К-33, А0). Windows 10/11, PowerShell 5.1+.
# Ноутбук подключён к точке доступа iPhone; сервер и Metro — на ноутбуке; Expo Go на том же iPhone.
# Никаких туннелей: всё только в локальной сети точки доступа.
#
# Запуск:   powershell -ExecutionPolicy Bypass -File deploy\windows\demo-start.ps1
# Правило брандмауэра (один раз, от имени администратора):
#           powershell -ExecutionPolicy Bypass -File deploy\windows\demo-start.ps1 -FirewallOnly
# Прогон реального магазина (К-37): отдельная база server\kaspi_test.db; подключение Kaspi и вход по коду
# включены только для этого запуска (server\.env не меняется); журнал сервера — в satti-backups:
#           powershell -ExecutionPolicy Bypass -File deploy\windows\demo-start.ps1 -KaspiTest
# Правило пускает на порты 8000 и 8081 только из локальной подсети (RemoteAddress LocalSubnet)
# и действует во всех профилях — в том числе когда Windows считает сеть «общественной».

param(
    [switch]$FirewallOnly,
    [switch]$KaspiTest,
    [int]$ApiPort = 8000,
    [int]$MetroPort = 8081
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$RuleName = "Satti demo (локальная подсеть)"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Set-DemoFirewall {
    if (-not (Test-Admin)) {
        Write-Host "Правило брандмауэра: запустите эту же команду с -FirewallOnly от имени администратора." -ForegroundColor Yellow
        return
    }
    Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $ApiPort, $MetroPort -RemoteAddress LocalSubnet -Profile Any | Out-Null
    Write-Host "Правило '$RuleName' создано: TCP $ApiPort, $MetroPort, только локальная подсеть, все профили сети."
}

function Get-DemoIp {
    $all = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }
    # точка доступа iPhone раздаёт адреса 172.20.10.x
    $hotspot = $all | Where-Object { $_.IPAddress -like "172.20.10.*" } | Select-Object -First 1
    if ($hotspot) { return $hotspot.IPAddress }
    $private = $all | Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)' } |
        Select-Object -First 1
    if ($private) {
        Write-Host "Точка доступа iPhone (172.20.10.x) не найдена — беру $($private.IPAddress)." -ForegroundColor Yellow
        return $private.IPAddress
    }
    throw "Нет адреса в локальной сети. Подключите ноутбук к точке доступа iPhone."
}

if ($FirewallOnly) { Set-DemoFirewall; exit 0 }

$ip = Get-DemoIp
$api = "http://${ip}:$ApiPort/v1"
Write-Host "Адрес ноутбука: $ip"

$rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if (-not $rule) { Write-Host "Внимание: нет правила брандмауэра. Без него iPhone может не достучаться." -ForegroundColor Yellow }

# Не засыпать во время встречи (от сети и от батареи); вернуть: powercfg /change standby-timeout-ac 30
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change standby-timeout-dc 0 | Out-Null
powercfg /change monitor-timeout-dc 0 | Out-Null

$server = Join-Path $Root "server"
$py = Join-Path $server ".venv\Scripts\python.exe"
$db = Join-Path $server "demo_phone.db"
$extraEnv = ""
if ($KaspiTest) {
    $db = Join-Path $server "kaspi_test.db"
    $backups = Join-Path (Split-Path $Root) "satti-backups"
    New-Item -ItemType Directory -Force $backups | Out-Null
    # копия базы до запуска; токен в ней зашифрован, копия остаётся на этом ноутбуке
    if (Test-Path $db) { Copy-Item $db (Join-Path $backups ("kaspi_test-before-{0:yyyyMMdd-HHmm}.db" -f (Get-Date))) }
    $logFile = Join-Path $backups ("kaspi_test_server_{0:yyyyMMdd}.log" -f (Get-Date))
    $extraEnv = "`$env:KASPI_ENABLED='1'; `$env:SATTI_EMAIL_LOGIN='1'; `$env:SATTI_LOG_FILE='$logFile'; "
    Write-Host "Режим К-37: база $db; журнал $logFile" -ForegroundColor Cyan
    Write-Host "Сводка прогона: server\.venv\Scripts\python.exe server\scripts\kaspi_watch.py --log `"$logFile`" --db `"$db`""
}
$serverCmd = $extraEnv + "`$env:DATABASE_URL='sqlite:///$($db -replace '\\','/')'; Set-Location '$server'; " +
    "& '$py' -m alembic upgrade head; & '$py' -m uvicorn app.main:app --host 0.0.0.0 --port $ApiPort"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $serverCmd -WindowStyle Normal

$mobile = Join-Path $Root "mobile"
$metroCmd = "`$env:EXPO_PUBLIC_API_URL='$api'; Remove-Item Env:CI -ErrorAction SilentlyContinue; " +
    "Set-Location '$mobile'; npx expo start --lan --port $MetroPort"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $metroCmd -WindowStyle Normal

# Ждём сервер до 60 секунд
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try { if ((Invoke-WebRequest "$api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $ok = $true; break } } catch {}
}
if ($ok) { Write-Host "Сервер отвечает: $api/health" -ForegroundColor Green }
else { Write-Host "Сервер не ответил за 60 секунд — смотрите окно сервера." -ForegroundColor Red }

Write-Host ""
Write-Host "На iPhone: Expo Go → Enter URL manually → exp://${ip}:$MetroPort" -ForegroundColor Cyan
