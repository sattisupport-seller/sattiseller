# К-33 А7: проверка перед меткой версии — одной командой. Итог — один файл с хэшем коммита: ЗЕЛЁНЫЙ или КРАСНЫЙ.
# Запуск из папки проекта (обычный PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\release_check.ps1
# Что проверяется (всё на этом коммите, рабочая папка должна быть чистой):
#   1. миграции на PostgreSQL: вверх → проверка «модели = миграции» → вниз до нуля → снова вверх;
#   2. полный pytest сервера на PostgreSQL;
#   3. линтер (ruff) и статический анализ безопасности (bandit, medium и выше);
#   4. аудит зависимостей сервера (pip-audit) и приложения (npm audit, продакшен);
#   5. поиск секретов по всей истории (gitleaks);
#   6. jest и проверка типов (tsc) приложения.
# Метку версии ставить только после ЗЕЛЁНОГО итога на этом же коммите; после него — ни одной правки без нового прогона.
# Требуется портативный PostgreSQL 16 (C:\Users\user\tools\pgsql, порт 55432) — скрипт запустит его сам.
param(
    [string]$PgBin = "C:\Users\user\tools\pgsql\bin",
    [string]$PgData = "C:\Users\user\tools\pgdata",
    [int]$PgPort = 55432,
    [string]$PgPassword = "satti",
    [string]$Gitleaks = "C:\Users\user\tools\gitleaks\gitleaks.exe",
    [switch]$AllowDirty  # только для отладки самого скрипта: итог всё равно будет КРАСНЫМ
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$server = Join-Path $Root "server"
$mobile = Join-Path $Root "mobile"
$py = Join-Path $server ".venv\Scripts\python.exe"
$outDir = Join-Path $Root "release-checks"
New-Item -ItemType Directory -Force $outDir | Out-Null

Set-Location $Root
$hash = (git rev-parse HEAD).Trim()
$short = $hash.Substring(0, 8)
$dirty = (git status --porcelain)
$started = Get-Date
$results = New-Object System.Collections.Generic.List[object]
$log = Join-Path $outDir ("{0:yyyyMMdd-HHmm}-{1}.log" -f $started, $short)
"release_check $hash $started" | Out-File $log -Encoding utf8

function Invoke-Step([string]$name, [scriptblock]$body) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    $t0 = Get-Date
    $ok = $false
    try {
        $out = & $body 2>&1
        $ok = ($LASTEXITCODE -eq 0) -or ($null -eq $LASTEXITCODE)
        $out | Out-File $log -Append -Encoding utf8
        $out | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
    } catch {
        $_ | Out-File $log -Append -Encoding utf8
        Write-Host $_ -ForegroundColor Red
        $ok = $false
    }
    $sec = [int]((Get-Date) - $t0).TotalSeconds
    $results.Add([pscustomobject]@{ Step = $name; Ok = $ok; Seconds = $sec })
    Write-Host ($(if ($ok) { "ОК" } else { "ОШИБКА" }) + " — $name ($sec с)") -ForegroundColor ($(if ($ok) { "Green" } else { "Red" }))
}

if ($dirty -and -not $AllowDirty) {
    Write-Host "Рабочая папка не чистая — сначала закоммитьте изменения (проверка относится к коммиту)." -ForegroundColor Red
    $dirty | Out-File $log -Append -Encoding utf8
    exit 2
}

# PostgreSQL: запустить, если не работает (отдельным процессом — окно не ждёт его завершения)
& "$PgBin\pg_isready.exe" -p $PgPort | Out-Null
if ($LASTEXITCODE -ne 0) {
    Start-Process -FilePath "$PgBin\pg_ctl.exe" -ArgumentList @("-D", $PgData, "-l", (Join-Path (Split-Path $PgData) "pg.log"), "-o", "`"-p $PgPort`"", "start") -WindowStyle Hidden
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep -Seconds 3; & "$PgBin\pg_isready.exe" -p $PgPort | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
$env:PGPASSWORD = $PgPassword
$pgUrl = "postgresql+psycopg://postgres:$PgPassword@127.0.0.1:$PgPort"

Invoke-Step "Миграции PostgreSQL: вверх → проверка моделей → вниз → вверх" {
    & "$PgBin\dropdb.exe" -h 127.0.0.1 -p $PgPort -U postgres --if-exists satti_release 2>&1
    & "$PgBin\createdb.exe" -h 127.0.0.1 -p $PgPort -U postgres satti_release 2>&1
    $env:DATABASE_URL = "$pgUrl/satti_release"
    $env:SATTI_ALLOW_DOWNGRADE = "1"
    Push-Location $server
    try {
        & $py -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw "upgrade head" }
        & $py -m alembic check; if ($LASTEXITCODE -ne 0) { throw "модели не совпадают с миграциями" }
        & $py -m alembic downgrade base; if ($LASTEXITCODE -ne 0) { throw "downgrade base" }
        & $py -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw "повторный upgrade head" }
    } finally {
        Pop-Location
        Remove-Item Env:DATABASE_URL, Env:SATTI_ALLOW_DOWNGRADE -ErrorAction SilentlyContinue
    }
}

Invoke-Step "pytest сервера на PostgreSQL" {
    $env:SATTI_TEST_DATABASE_URL = "$pgUrl/satti_test"
    $env:PYTHONIOENCODING = "utf-8"
    Push-Location $server
    try { & $py -m pytest -q --no-header -p no:cacheprovider } finally { Pop-Location; Remove-Item Env:SATTI_TEST_DATABASE_URL -ErrorAction SilentlyContinue }
}

Invoke-Step "ruff (линтер)" { Push-Location $server; try { & (Join-Path $server ".venv\Scripts\ruff.exe") check app tests } finally { Pop-Location } }
Invoke-Step "bandit (безопасность, medium и выше)" { Push-Location $server; try { & (Join-Path $server ".venv\Scripts\bandit.exe") -r app -ll -q } finally { Pop-Location } }
Invoke-Step "pip-audit (зависимости сервера)" { Push-Location $server; try { & (Join-Path $server ".venv\Scripts\pip-audit.exe") -r requirements.txt } finally { Pop-Location } }
Invoke-Step "gitleaks (секреты по всей истории)" { & $Gitleaks detect --source $Root --log-opts="--all" --redact --no-banner }
Invoke-Step "jest (приложение)" { Push-Location $mobile; try { npx jest --silent } finally { Pop-Location } }
Invoke-Step "tsc (проверка типов)" { Push-Location $mobile; try { npx tsc --noEmit } finally { Pop-Location } }
Invoke-Step "npm audit (зависимости приложения, продакшен)" { Push-Location $mobile; try { npm audit --omit=dev --audit-level=high } finally { Pop-Location } }

$green = (-not $dirty) -and -not ($results | Where-Object { -not $_.Ok })
$verdict = if ($green) { "ЗЕЛЁНЫЙ" } else { "КРАСНЫЙ" }
$file = Join-Path $outDir ("{0:yyyyMMdd-HHmm}-{1}-{2}.txt" -f $started, $short, $(if ($green) { "green" } else { "red" }))
$lines = @("release_check: $verdict", "коммит: $hash", "начало: $started", "конец: $(Get-Date)", "")
if ($dirty) { $lines += "рабочая папка была не чистой — итог недействителен" }
foreach ($r in $results) { $lines += ("{0,-8} {1} ({2} с)" -f $(if ($r.Ok) { "ОК" } else { "ОШИБКА" }), $r.Step, $r.Seconds) }
$lines += "", "подробный журнал: $log"
$lines | Out-File $file -Encoding utf8
Write-Host ""
$lines | ForEach-Object { Write-Host $_ }
Write-Host "`nИтог: $verdict → $file" -ForegroundColor ($(if ($green) { "Green" } else { "Red" }))
if ($green) { exit 0 } else { exit 1 }
