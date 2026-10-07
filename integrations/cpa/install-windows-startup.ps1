$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$supervisor = Join-Path $PSScriptRoot 'windows-supervisor.ps1'
$launcher = Join-Path $PSScriptRoot 'launch-hidden.vbs'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$command = '"' + $powershell + '" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $supervisor + '"'
$vbsCommand = $command.Replace('"', '""')
Set-Content -LiteralPath $launcher -Encoding Unicode -Value @"
Set shell = CreateObject("WScript.Shell")
shell.Run "$vbsCommand", 0, False
"@
$wsh = New-Object -ComObject WScript.Shell
foreach ($shortcutDirectory in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'))) {
    $shortcutPath = Join-Path $shortcutDirectory 'Token Monitor CPA.lnk'
    if (Test-Path -LiteralPath $shortcutPath) { Copy-Item -LiteralPath $shortcutPath -Destination ($shortcutPath + '.pre-cpa.bak') }
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $shortcut.Arguments = '"' + $launcher + '"'
    $shortcut.WorkingDirectory = $taskRoot
    $shortcut.IconLocation = (Join-Path $taskRoot 'dist\win-unpacked\Token Monitor.exe') + ',0'
    $shortcut.Description = 'Token Monitor with CPA quotas from maxim'
    $shortcut.Save()
    Write-Output "Created $shortcutPath"
}
