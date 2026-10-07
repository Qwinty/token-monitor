param(
    [string]$SshHost = 'maxim',
    [int]$LocalPort = 17321,
    [int]$RemotePort = 17321
)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$logPath = Join-Path $taskRoot 'data\windows-supervisor.log'
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'data') -Force | Out-Null
$taskMutex = New-Object System.Threading.Mutex($false, 'Local\TokenMonitorCPAWindowsSupervisor')
$appPath = Join-Path $taskRoot 'dist\win-unpacked\Token Monitor.exe'
if (-not $taskMutex.WaitOne(0)) {
    Start-Process -FilePath $appPath -WorkingDirectory $taskRoot -WindowStyle Hidden
    $taskMutex.Dispose()
    exit 0
}
$tunnel = $null
try {
    if (-not (Test-Path -LiteralPath $appPath)) { throw "Packaged application is missing: $appPath" }
    Start-Process -FilePath $appPath -WorkingDirectory $taskRoot -WindowStyle Hidden
    while ($true) {
        try {
            # Own only this SSH process; never terminate unrelated tunnels or apps.
            $tunnel = Start-Process -FilePath "$env:WINDIR\System32\OpenSSH\ssh.exe" -ArgumentList @(
                '-N', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
                '-o', 'ExitOnForwardFailure=yes', '-L', "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}", $SshHost
            ) -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $taskRoot 'data\ssh-tunnel.log')
            Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) tunnel started, pid $($tunnel.Id)"
            $tunnel.WaitForExit()
            Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) tunnel exited: $($tunnel.ExitCode); retrying in 10s"
        } catch {
            Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 10
    }
} finally {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue }
    $taskMutex.ReleaseMutex()
    $taskMutex.Dispose()
}
