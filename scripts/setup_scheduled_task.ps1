# Setup Windows Task Scheduler for Paper Trading
# Run this script as Administrator:
#   Right-click PowerShell > Run as Administrator
#   cd C:\Users\vkudu\claude-projects\tradovate-futures-bot
#   .\setup_scheduled_task.ps1

$taskName = "Tradovate Paper Trading"
$taskPath = "C:\Users\vkudu\claude-projects\tradovate-futures-bot"
$batFile = "$taskPath\start_paper_trading.bat"

# Remove existing task if present
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Create the action (run the batch file)
$action = New-ScheduledTaskAction -Execute $batFile -WorkingDirectory $taskPath

# Create triggers for weekdays at 3:55 AM ET (before 4 AM market open)
$triggers = @()
# Monday through Friday
for ($day = 1; $day -le 5; $day++) {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $day -At "3:55AM"
    $triggers += $trigger
}

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Hours 14) `
    -MultipleInstances IgnoreNew

# Create principal (run whether user is logged on or not)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

# Register the task
Write-Host "Creating scheduled task: $taskName" -ForegroundColor Green
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs V10.8 paper trading bot every weekday from 4 AM to 4:30 PM ET"

Write-Host ""
Write-Host "Task created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Schedule: Monday-Friday at 3:55 AM" -ForegroundColor Cyan
Write-Host "Features:" -ForegroundColor Cyan
Write-Host "  - Auto-starts before market open" -ForegroundColor White
Write-Host "  - Auto-restarts on crash (up to 5x/day)" -ForegroundColor White
Write-Host "  - Stops automatically at market close" -ForegroundColor White
Write-Host "  - Logs saved to: logs\paper_trading\" -ForegroundColor White
Write-Host ""
Write-Host "To test now: schtasks /run /tn `"$taskName`"" -ForegroundColor Yellow
Write-Host "To view task: taskschd.msc" -ForegroundColor Yellow
Write-Host "To remove: Unregister-ScheduledTask -TaskName `"$taskName`"" -ForegroundColor Yellow
