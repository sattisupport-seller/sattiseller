# Демо Satti на iPhone через Expo Go — одной командой (К-33, А0). Windows 10/11, PowerShell 5.1+.
# Ноутбук подключён к точке доступа iPhone; сервер и Metro — на ноутбуке; Expo Go на том же iPhone.
# Никаких туннелей: всё только в локальной сети точки доступа.
#
# Запуск:   powershell -ExecutionPolicy Bypass -File deploy\windows\demo-start.ps1
# Правило брандмауэра (один раз, от имени администратора):
#           powershell -ExecutionPolicy Bypass -File deploy\windows\demo-start.ps1 -FirewallOnly
# Правило пускает на порты 8000 и 8081 только из локальной подсети (RemoteAddress LocalSubnet)
# и действует во всех профилях — в том числе когда Windows считает сеть «общественной».

param(
    [switch]$FirewallOnly,
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
$serverCmd = "`$env:DATABASE_URL='sqlite:///$($db -replace '\\','/')'; Set-Location '$server'; " +
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
