# К-33 А6: последний код входа из папки outbox (на ноутбуке нет почтового сервиса — письма с кодами пишутся в файлы).
# Запуск из папки проекта: powershell -ExecutionPolicy Bypass -File deploy\windows\last-code.ps1
# Показывает адрес и код из последнего письма. Код действует несколько минут.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$serverDir = Join-Path $Root "server"
$envFile = Join-Path $serverDir ".env"
$outbox = $null
if (Test-Path $envFile) {
    foreach ($raw in Get-Content $envFile -Encoding UTF8) {
        $line = $raw.TrimStart([char]0xFEFF)
        if ($line -match "^SATTI_OUTBOX_DIR=(.+)$") { $outbox = $Matches[1].Trim().Trim('"') }
    }
    if (-not $outbox) {
        foreach ($raw in Get-Content $envFile -Encoding UTF8) {
            $line = $raw.TrimStart([char]0xFEFF)
            if ($line -match "^SATTI_DATA_DIR=(.+)$") { $outbox = Join-Path $Matches[1].Trim().Trim('"') "outbox" }
        }
    }
}
if (-not $outbox) { $outbox = Join-Path (Join-Path $serverDir "data") "outbox" }
if (-not [System.IO.Path]::IsPathRooted($outbox)) { $outbox = Join-Path $serverDir $outbox }
$last = Get-ChildItem -Path $outbox -Filter *.eml -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $last) { Write-Host "Писем нет в $outbox — сначала нажмите «Получить код» в приложении или админке."; exit 1 }
$text = Get-Content $last.FullName -Raw -Encoding UTF8
$to = ([regex]::Match($text, "(?m)^To: (.+)$")).Groups[1].Value.Trim()
$code = ([regex]::Match($text, "Ваш код: (\S+)")).Groups[1].Value
Write-Host ("Кому: " + $to)
Write-Host ("Код:  " + $code + "   (письмо " + $last.LastWriteTime.ToString("HH:mm:ss") + ")")
