# ФАЙЛ ДЛЯ ПАПКИ: D:\Проэеты\Pon_Bots
# КУДА ВСТАВЛЯТЬ: D:\Проэеты\Pon_Bots\bots.ps1
#
# Использование (из PowerShell, находясь в любой папке):
#   D:\Проэеты\Pon_Bots\bots.ps1 start    — запустить все 4 бота в фоне
#   D:\Проэеты\Pon_Bots\bots.ps1 stop     — остановить все 4 бота
#   D:\Проэеты\Pon_Bots\bots.ps1 status   — проверить, кто из ботов работает
#   D:\Проэеты\Pon_Bots\bots.ps1 restart  — остановить и запустить заново
#
# Логи каждого бота — в его собственной папке: bot.log (обычный вывод)
# и bot_error.log (ошибки), например D:\Проэеты\Pon_Bots\Mafia\bot.log

param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "restart")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"

$Bots = @(
    @{ Name = "Mafia";  Path = "D:\Проэеты\Pon_Bots\Mafia" },
    @{ Name = "Bunker"; Path = "D:\Проэеты\Pon_Bots\bunker_bot" },
    @{ Name = "Table";  Path = "D:\Проэеты\Pon_Bots\table_bot" },
    @{ Name = "Casino"; Path = "D:\Проэеты\Pon_Bots\casino_bot" }
)

$PidFile = Join-Path $PSScriptRoot "bots.pid"


function Start-AllBots {
    if (Test-Path $PidFile) {
        Write-Host "⚠️  Файл bots.pid уже существует — похоже, боты уже запущены." -ForegroundColor Yellow
        Write-Host "    Сначала выполните: bots.ps1 stop" -ForegroundColor Yellow
        return
    }

    foreach ($bot in $Bots) {
        $venvPython = Join-Path $bot.Path "venv\Scripts\python.exe"
        $botScript = Join-Path $bot.Path "bot.py"

        if (-not (Test-Path $venvPython)) {
            Write-Host "❌ $($bot.Name): не найден $venvPython — пропускаю" -ForegroundColor Red
            continue
        }
        if (-not (Test-Path $botScript)) {
            Write-Host "❌ $($bot.Name): не найден $botScript — пропускаю" -ForegroundColor Red
            continue
        }

        $logOut = Join-Path $bot.Path "bot.log"
        $logErr = Join-Path $bot.Path "bot_error.log"

        $proc = Start-Process -FilePath $venvPython `
            -ArgumentList "bot.py" `
            -WorkingDirectory $bot.Path `
            -WindowStyle Hidden `
            -RedirectStandardOutput $logOut `
            -RedirectStandardError $logErr `
            -PassThru

        "$($bot.Name)=$($proc.Id)" | Add-Content $PidFile
        Write-Host "✅ $($bot.Name) запущен (PID $($proc.Id))" -ForegroundColor Green
    }

    Write-Host "`nГотово. Можно закрывать это окно PowerShell — боты продолжат работать в фоне."
    Write-Host "Логи — в bot.log / bot_error.log внутри папки каждого бота."
}


function Stop-AllBots {
    if (-not (Test-Path $PidFile)) {
        Write-Host "Файл bots.pid не найден — похоже, боты не запускались этим скриптом." -ForegroundColor Yellow
        return
    }

    Get-Content $PidFile | ForEach-Object {
        if ($_ -match "^(.+)=(\d+)$") {
            $name = $Matches[1]
            $procId = [int]$Matches[2]
            try {
                Stop-Process -Id $procId -ErrorAction Stop
                Write-Host "🛑 $name (PID $procId) остановлен" -ForegroundColor Green
            } catch {
                Write-Host "⚠️  $name (PID $procId) уже не был запущен" -ForegroundColor Yellow
            }
        }
    }

    Remove-Item $PidFile
}


function Get-AllBotsStatus {
    if (-not (Test-Path $PidFile)) {
        Write-Host "Файл bots.pid не найден — боты либо не запускались этим скриптом, либо уже остановлены."
        return
    }

    Get-Content $PidFile | ForEach-Object {
        if ($_ -match "^(.+)=(\d+)$") {
            $name = $Matches[1]
            $procId = [int]$Matches[2]
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "✅ $name (PID $procId) работает" -ForegroundColor Green
            } else {
                Write-Host "❌ $name (PID $procId) не запущен" -ForegroundColor Red
            }
        }
    }
}


switch ($Action) {
    "start" { Start-AllBots }
    "stop" { Stop-AllBots }
    "status" { Get-AllBotsStatus }
    "restart" {
        Stop-AllBots
        Start-Sleep -Seconds 2
        Start-AllBots
    }
}
