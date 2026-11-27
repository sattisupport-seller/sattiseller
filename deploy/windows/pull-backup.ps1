# Еженедельная копия базы Satti на компьютер владельца (К-21, часть 2, п.10). Windows 10/11, PowerShell 5.1+.
# Копия уже зашифрована на сервере (ключ SATTI_BACKUP_KEY — в менеджере паролей, НЕ рядом с копиями).
# Нужен вход на сервер по SSH-ключу (OpenSSH входит в Windows). Настройки — в начале файла.
# Запуск вручную:  powershell -ExecutionPolicy Bypass -File pull-backup.ps1
# Каждую неделю: Планировщик заданий → см. docs/OPERATIONS.md, «Копия на компьютер владельца».

$Server   = "satti@<IP или домен сервера>"   # пользователь и адрес сервера
$DeployDir = "/opt/satti/deploy"             # где лежит deploy.sh на сервере
$Target   = Join-Path $env:USERPROFILE "Documents\Satti-backups"
$Keep     = 8                                # хранить последние 8 копий (два месяца)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$log = Join-Path $Target "pull-backup.log"

try {
    $name = (ssh -o BatchMode=yes $Server "cd $DeployDir && ./deploy.sh export-latest" | Select-Object -Last 1).Trim()
    if (-not ($name -like "satti-*.bak")) { throw "сервер не вернул имя копии: $name" }
    scp -o BatchMode=yes "${Server}:~/satti-export/$name" (Join-Path $Target $name)
    if ((Get-Item (Join-Path $Target $name)).Length -lt 1024) { throw "файл копии подозрительно мал" }
    Get-ChildItem $Target -Filter "satti-*.bak" | Sort-Object Name -Descending | Select-Object -Skip $Keep | Remove-Item -Force
    Add-Content $log "$(Get-Date -Format s) ok $name"
} catch {
    Add-Content $log "$(Get-Date -Format s) ОШИБКА $($_.Exception.Message)"
    # заметное уведомление владельцу на этом компьютере
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Копия Satti не скачана: $($_.Exception.Message)", "Satti — копия базы") | Out-Null
    exit 1
}
