# 一键部署脚本。
# 用法：
#   .\upload.ps1                         上传并完整部署/更新服务（如存在 QQ.txt 会自动同步密码兜底）
#   .\upload.ps1 -Start                  远程启动服务（读取 key.txt 的 SSH 凭据）
#   .\upload.ps1 -Stop                   远程停止服务
#   .\upload.ps1 -Status                 查看远程服务状态
#   .\upload.ps1 -SyncKey                只同步服务器 Token 到本机 key.txt
#   .\upload.ps1 -SyncPassword           只把 QQ.txt 同步到服务器密码兜底文件
#   .\upload.ps1 -Connect                打开服务器 SSH 终端
#   .\upload.ps1 -PrepareOnly            只准备上传包
param(
    [switch]$SyncKey,
    [switch]$Connect,
    [switch]$PrepareOnly,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$SyncPassword,
    [string[]]$StartArgs = @(),
    [string[]]$StopArgs = @()
)

$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
Set-Location -LiteralPath $taskRoot

$taskActionCount = @(@($SyncKey, $Connect, $PrepareOnly, $Start, $Stop, $Status, $SyncPassword) | Where-Object { $_ }).Count
if ($taskActionCount -gt 1) {
    throw 'Use only one of -SyncKey, -Connect, -PrepareOnly, -Start, -Stop, -Status or -SyncPassword at a time.'
}
if ($StartArgs.Count -gt 0 -and -not $Start) { throw '-StartArgs can only be used together with -Start.' }
if ($StopArgs.Count -gt 0 -and -not $Stop) { throw '-StopArgs can only be used together with -Stop.' }

function Read-KeyFile([string]$Path) {
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($Path, [Text.Encoding]::UTF8)) {
        if (-not $line.Trim() -or $line.TrimStart().StartsWith('#')) { continue }
        if ($line.Trim() -match '^(AstrBot|NapCat):\s*https?://\S+$') { continue }
        $parts = $line.Split([char[]]'=', 2, [StringSplitOptions]::None)
        if ($parts.Count -ne 2 -or $values.ContainsKey($parts[0].Trim())) {
            throw 'Invalid or duplicate field in key.txt. Follow key.example.txt.'
        }
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Invoke-SshKeyTool([string]$Program, [string[]]$ToolArguments, [int[]]$SuccessCodes = @(0)) {
    $savedPreference = $ErrorActionPreference
    try {
        # Discovery may report an authentication refusal after saving the host key.
        $ErrorActionPreference = 'Continue'
        $output = @(& $Program @ToolArguments 2>$null)
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    if ($SuccessCodes -notcontains $code) {
        throw "$Program failed during SSH host-key verification (exit $code). Check the server address, port 22 and network."
    }
    return $output
}

function Confirm-SshHostKey([string]$Server, [string]$KnownHosts, [string]$TempDirectory, [string]$User = 'root') {
    $newKeyFile = Join-Path $TempDirectory 'host-key.pub'
    $oldKeyFile = Join-Path $TempDirectory 'previous-host-keys'
    try {
        # Windows ssh-keyscan 9.5 cannot negotiate some Ubuntu 26.04 KEX algorithms.
        # Discover into a private temporary file with every credential method disabled.
        [IO.File]::WriteAllText($newKeyFile, '', [Text.UTF8Encoding]::new($false))
        Push-Location -LiteralPath $TempDirectory
        try {
            Invoke-SshKeyTool 'ssh.exe' @('-p', '22', '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
                '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=host-key.pub',
                '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'UpdateHostKeys=no', '-o', 'HashKnownHosts=no',
                '-o', "HostKeyAlias=$Server",
                '-o', 'ControlPath=none', '-o', 'BatchMode=yes', '-o', 'PreferredAuthentications=none',
                '-o', 'PubkeyAuthentication=no', '-o', 'PasswordAuthentication=no',
                '-o', 'KbdInteractiveAuthentication=no', "${User}@${Server}", 'exit') @(0, 255) | Out-Null
        } finally { Pop-Location }
        $scanned = [IO.File]::ReadAllLines($newKeyFile)
        $newKeys = @($scanned | Where-Object { $_ -match '^\S+\s+ssh-ed25519\s+[A-Za-z0-9+/]+={0,2}\s*$' } |
            ForEach-Object { "${Server} ssh-ed25519 $(($_ -split '\s+')[2])" } | Sort-Object -Unique)
        if ($newKeys.Count -ne 1) { throw 'Could not obtain one unambiguous ED25519 host key. Check the server address, port 22 and network. No host records were changed.' }
        [IO.File]::WriteAllText($newKeyFile, $newKeys[0] + "`n", [Text.UTF8Encoding]::new($false))
        $fingerprint = @(Invoke-SshKeyTool 'ssh-keygen.exe' @('-l', '-f', $newKeyFile, '-E', 'sha256'))
        $records = @()
        if (Test-Path -LiteralPath $KnownHosts) {
            $records = @(Invoke-SshKeyTool 'ssh-keygen.exe' @('-F', $Server, '-f', $KnownHosts) @(0, 1) |
                Where-Object { $_.Trim() -and -not $_.StartsWith('#') })
        }
        if (@($records | Where-Object { $_ -match '^@' }).Count) {
            throw 'This host has a revoked-key or certificate-authority record. Review known_hosts manually; it was not changed.'
        }
        $key = ($newKeys[0] -split '\s+')[2]
        if (@($records | Where-Object { $_ -match ('^\S+\s+ssh-ed25519\s+' + [regex]::Escape($key) + '(?:\s|$)') }).Count) {
            return
        }
        $otherRecords = @(foreach ($record in $records) {
            $aliases = ($record -split '\s+')[0] -split ','
            if (@($aliases | Where-Object { $_ -match '[*?!]' }).Count) {
                throw 'This host uses a known_hosts pattern. Review that entry manually; it was not changed.'
            }
            $remaining = @($aliases | Where-Object { $_ -ine $Server -and -not $_.StartsWith('|') })
            if ($remaining.Count) { $record -replace '^\S+', ($remaining -join ',') }
        })
        Write-Host "SSH server: ${Server}:22"
        if ($records.Count) {
            [IO.File]::WriteAllLines($oldKeyFile, [string[]]$records, [Text.UTF8Encoding]::new($false))
            Write-Host 'Previously saved host key(s):'
            Invoke-SshKeyTool 'ssh-keygen.exe' @('-l', '-f', $oldKeyFile, '-E', 'sha256') | ForEach-Object { Write-Host $_ }
            Write-Host 'Current ED25519 host key:'
            $fingerprint | ForEach-Object { Write-Host $_ }
            Write-Host 'The saved key differs. Verify this fingerprint in the server console, especially after reinstalling Ubuntu.'
            $answer = Read-Host 'Type YES to replace this server record and continue (Enter cancels)'
            if ($answer -cne 'YES') { throw 'Host-key update cancelled. Existing host records were not changed.' }
            Invoke-SshKeyTool 'ssh-keygen.exe' @('-R', $Server, '-f', $KnownHosts) | Out-Null
            Write-Host "Previous records backed up to ${KnownHosts}.old"
        } else {
            $fingerprint | ForEach-Object { Write-Host $_ }
            Write-Host 'First connection: saving this server host key.'
            [IO.Directory]::CreateDirectory((Split-Path -Parent $KnownHosts)) | Out-Null
        }
        $replacement = (@($otherRecords) + $newKeys[0]) -join "`n"
        [IO.File]::AppendAllText($KnownHosts, "`n" + $replacement + "`n", [Text.UTF8Encoding]::new($false))
    } finally {
        foreach ($file in @($newKeyFile, $oldKeyFile)) {
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
        }
    }
}

function Invoke-OpenSsh([string]$Program, [string[]]$ToolArguments,
    [string]$FailureMessage = 'SSH failed. Check the host-key warning, SSH credentials and network access.',
    [int[]]$AllowedExitCodes = @(0)) {
    $saved = @{}
    foreach ($name in @('SSH_ASKPASS', 'SSH_ASKPASS_REQUIRE', 'DAFEIYU_CREDENTIAL_FILE')) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        $env:SSH_ASKPASS = $taskAskPass
        $env:SSH_ASKPASS_REQUIRE = 'force'
        $env:DAFEIYU_CREDENTIAL_FILE = $taskKeyPath
        & $Program @ToolArguments
        $script:taskLastExitCode = $LASTEXITCODE
        if ($AllowedExitCodes -notcontains $LASTEXITCODE) { throw ($FailureMessage + " Exit code: $LASTEXITCODE") }
    } finally {
        foreach ($name in $saved.Keys) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
        }
    }
}

function Sync-ServerTokens {
    Invoke-OpenSsh 'scp.exe' ($taskCommon + @('-P', '22', "${taskTarget}:dafeiyu/key.txt", $taskDownloaded))
    $remoteKeys = Read-KeyFile $taskDownloaded
    if ($remoteKeys['SSH_HOST'] -ne $taskAddress -or -not $remoteKeys['NAPCAT_TOKEN'] -or -not $remoteKeys['ONEBOT_TOKEN']) {
        throw 'Downloaded key.txt does not match this server, or the NapCat/OneBot tokens are missing.'
    }
    $updates = @{'NAPCAT_TOKEN' = $remoteKeys['NAPCAT_TOKEN']; 'ONEBOT_TOKEN' = $remoteKeys['ONEBOT_TOKEN']}
    $lines = [Collections.Generic.List[string]]::new()
    foreach ($line in [IO.File]::ReadAllLines($taskKeyPath, [Text.Encoding]::UTF8)) {
        if ($line.Trim() -match '^(AstrBot|NapCat):\s*https?://\S+$') { continue }
        $name = $line.Split([char[]]'=', 2, [StringSplitOptions]::None)[0].Trim()
        if (-not $line.TrimStart().StartsWith('#') -and $updates.ContainsKey($name)) {
            $lines.Add("${name}=$($updates[$name])")
            $updates.Remove($name)
        } else { $lines.Add($line) }
    }
    foreach ($name in @($updates.Keys)) { $lines.Add("${name}=$($updates[$name])") }
    while ($lines.Count -and -not $lines[$lines.Count - 1].Trim()) { $lines.RemoveAt($lines.Count - 1) }
    $lines.Add('')
    $lines.Add("AstrBot: http://${taskAddress}:6185/")
    $lines.Add("NapCat:  http://${taskAddress}:6099/webui/web_login")
    $keyItem = Get-Item -LiteralPath $taskKeyPath
    if ($keyItem.IsReadOnly) {
        $keyItem.IsReadOnly = $false
        Write-Host 'Cleared the read-only flag on local key.txt before updating it.'
    }
    for ($retry = 0; ; $retry++) {
        try {
            [IO.File]::WriteAllLines($taskKeyPath, $lines, [Text.UTF8Encoding]::new($false))
            break
        } catch {
            $denied = $_.Exception -is [System.UnauthorizedAccessException] -or $_.Exception -is [System.IO.IOException]
            if ($denied -and $retry -eq 0) {
                Start-Sleep -Milliseconds 800
                continue
            }
            throw
        }
    }
    Write-Host 'NapCat/OneBot tokens and service URLs saved to local key.txt. Other local fields were preserved.'
}

function Invoke-RemoteServiceScript([string]$ScriptName, [string[]]$ScriptArguments, [int[]]$AllowedExitCodes = @(0)) {
    $quoted = @()
    foreach ($argument in $ScriptArguments) {
        $quoted += "'" + $argument.Replace("'", "'\''") + "'"
    }
    $argumentsText = if ($quoted.Count) { ' ' + ($quoted -join ' ') } else { '' }
    $remoteCommand = 'cd "$HOME/dafeiyu" || { echo "Missing ~/dafeiyu; run upload.ps1 deployment first."; exit 2; }; ' +
        'if [ ! -f ' + $ScriptName + ' ]; then echo "Missing ~/dafeiyu/' + $ScriptName + '; redeploy with upload.ps1 first."; exit 2; fi; ' +
        'if [ "$(id -u)" -eq 0 ]; then bash ' + $ScriptName + $argumentsText + '; else sudo -n bash ' + $ScriptName + $argumentsText + '; fi'
    Invoke-OpenSsh 'ssh.exe' ($taskCommon + @('-p', '22', $taskTarget, $remoteCommand)) "Remote $ScriptName failed." $AllowedExitCodes
}

function Read-QqPasswordFile([string]$Path) {
    # Parses QQ.txt without ever echoing its values. Only the three known fields are accepted.
    $values = @{}
    foreach ($line in [IO.File]::ReadAllLines($Path, [Text.Encoding]::UTF8)) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $parts = $line.Split([char[]]'=', 2, [StringSplitOptions]::None)
        if ($parts.Count -ne 2) { throw 'QQ.txt has an invalid line (expected NAME=VALUE).' }
        $name = $parts[0].Trim().ToUpperInvariant()
        if (@('QQ_ACCOUNT', 'QQ_PASSWORD', 'QQ_PASSWORD_MD5') -notcontains $name) {
            throw "QQ.txt contains an unsupported field: $name"
        }
        if ($values.ContainsKey($name)) { throw "QQ.txt contains a duplicate field: $name" }
        $values[$name] = $parts[1].Trim()
    }
    $account = $values['QQ_ACCOUNT']
    $password = $values['QQ_PASSWORD']
    $md5 = $values['QQ_PASSWORD_MD5']
    if ($account -and $account -notmatch '^[0-9]{5,12}$') { throw 'QQ.txt QQ_ACCOUNT is not a valid QQ number.' }
    if ($md5 -and $md5 -notmatch '^[a-fA-F0-9]{32}$') { throw 'QQ.txt QQ_PASSWORD_MD5 must be 32 hex characters.' }
    if (-not $password -and -not $md5) { throw 'QQ.txt must contain QQ_PASSWORD or QQ_PASSWORD_MD5.' }
    return @{
        Account = $account
        Password = $password
        Md5 = $(if ($md5) { $md5.ToLowerInvariant() } else { '' })
    }
}

function Sync-QqPasswordFile([string]$Path) {
    $secret = Read-QqPasswordFile $Path
    $lines = @()
    if ($secret.Account) { $lines += 'QQ_ACCOUNT=' + $secret.Account }
    if ($secret.Password) { $lines += 'QQ_PASSWORD=' + $secret.Password } else { $lines += 'QQ_PASSWORD_MD5=' + $secret.Md5 }
    [IO.File]::WriteAllText($taskQqSecret, (($lines -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
    $prepare = 'set -eu; umask 077; mkdir -p "$HOME/dafeiyu/secret"; chmod 700 "$HOME/dafeiyu/secret"'
    Invoke-OpenSsh 'ssh.exe' ($taskCommon + @('-p', '22', $taskTarget, $prepare)) 'Could not prepare the server password directory.'
    Invoke-OpenSsh 'scp.exe' ($taskCommon + @('-P', '22', $taskQqSecret, "${taskTarget}:dafeiyu/secret/.qq-login.incoming")) 'Could not upload QQ.txt to the server.'
    $finalize = 'set -eu; umask 077; chmod 600 "$HOME/dafeiyu/secret/.qq-login.incoming"; mv -f "$HOME/dafeiyu/secret/.qq-login.incoming" "$HOME/dafeiyu/secret/qq-login.txt"; chmod 600 "$HOME/dafeiyu/secret/qq-login.txt"'
    Invoke-OpenSsh 'ssh.exe' ($taskCommon + @('-p', '22', $taskTarget, $finalize)) 'Could not secure the server password file.'
    Write-Host 'QQ.txt synced to server ~/dafeiyu/secret/qq-login.txt (mode 600; content not shown).'
}

$taskKeyPath = Join-Path $taskRoot 'key.txt'
if (-not (Test-Path -LiteralPath $taskKeyPath)) {
    throw 'Missing key.txt. Create it using the fields documented in README.md.'
}
$taskKeys = Read-KeyFile $taskKeyPath
$taskAddress = $taskKeys['SSH_HOST']
$taskUser = $taskKeys['SSH_USER']
if ($taskAddress -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]*$' -or
    $taskUser -notmatch '^[a-z_][a-z0-9_-]*[$]?$') {
    throw 'Invalid SSH_HOST or SSH_USER in key.txt.'
}
if (-not $taskKeys['SSH_PASSWORD']) { throw 'Fill SSH_PASSWORD in key.txt.' }
$taskTarget = "${taskUser}@${taskAddress}"
$taskTemp = Join-Path ([IO.Path]::GetTempPath()) ('dafeiyu-upload-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskTemp | Out-Null
$taskArchive = Join-Path $taskTemp 'upload.tar.gz'
$taskAskPass = Join-Path $taskTemp 'ssh-askpass.exe'
$taskDownloaded = Join-Path $taskTemp 'server-key.txt'
$taskQqFile = Join-Path $taskRoot 'QQ.txt'
$taskQqSecret = Join-Path $taskTemp 'qq-login.txt'
$taskHasQqFile = Test-Path -LiteralPath $taskQqFile
$taskKeepArchive = $false

try {

    if (-not $SyncKey -and -not $Connect -and -not $Start -and -not $Stop -and -not $Status -and -not $SyncPassword) {
        if ($taskHasQqFile) { $null = Read-QqPasswordFile $taskQqFile }
        if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) {
            throw 'Windows 10/11 tar.exe is required. Update Windows and try again.'
        }
        $taskFiles = @('key.txt', 'deploy.sh', 'configure.py', 'compose.yaml', 'qq_watchdog.py', 'start.sh', 'stop.sh', 'pack')
        foreach ($taskFile in $taskFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $taskRoot $taskFile))) {
                throw "Missing deployment file: $taskFile"
            }
        }
        & tar.exe -czf $taskArchive --exclude=__pycache__ '--exclude=*.pyc' -C $taskRoot @taskFiles
        if ($LASTEXITCODE -ne 0) { throw 'Could not create upload archive.' }
        if ($PrepareOnly) {
            $taskKeepArchive = $true
            Write-Host 'Temporary archive prepared; remove it after transfer. It contains credentials.'
            Write-Output $taskArchive
            return
        }
    }

    foreach ($taskProgram in @('ssh.exe', 'scp.exe', 'ssh-keygen.exe')) {
        if (-not (Get-Command $taskProgram -ErrorAction SilentlyContinue)) {
            throw 'Enable the complete Windows OpenSSH Client optional feature first. See README.md.'
        }
    }
    $taskKnownHosts = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.ssh\known_hosts'
    Confirm-SshHostKey $taskAddress $taskKnownHosts $taskTemp $taskUser
    $taskAskPassSource = Join-Path $taskRoot 'ssh-askpass.cs'
    if (-not (Test-Path -LiteralPath $taskAskPassSource)) { throw 'Missing ssh-askpass.cs.' }
    if (-not (Test-Path -LiteralPath $taskAskPass) -or
        (Get-Item -LiteralPath $taskAskPassSource).LastWriteTimeUtc -gt (Get-Item -LiteralPath $taskAskPass).LastWriteTimeUtc) {
        $taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        if (-not (Test-Path -LiteralPath $taskCompiler)) {
            $taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
        }
        if (-not (Test-Path -LiteralPath $taskCompiler)) { throw 'Windows .NET Framework 4 compiler is unavailable.' }
        & $taskCompiler /nologo /target:winexe ("/out:$taskAskPass") $taskAskPassSource
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the SSH password helper.' }
    }
    $taskCommon = @('-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile=~/.ssh/known_hosts', '-o', 'HostKeyAlgorithms=ssh-ed25519',
        '-o', 'UpdateHostKeys=no', '-o', 'ControlPath=none', '-o', "HostKeyAlias=$taskAddress",
        '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=20',
        '-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no',
        '-o', 'PasswordAuthentication=yes', '-o', 'NumberOfPasswordPrompts=1')
    Write-Host 'Reading SSH credentials from key.txt automatically.'
    if ($Status) {
        Invoke-RemoteServiceScript 'start.sh' @('--status') @(0, 1)
        if ($script:taskLastExitCode -eq 1) {
            Write-Host 'AstrBot/NapCat are not running. Use -Start to start them.'
        }
        return
    }
    if ($SyncPassword) {
        if (-not $taskHasQqFile) { throw 'QQ.txt not found in the project directory.' }
        Sync-QqPasswordFile $taskQqFile
        return
    }
    if ($Start) {
        Write-Host 'Starting services on the server...'
        Invoke-RemoteServiceScript 'start.sh' $StartArgs
        Write-Host 'Start command completed.'
        return
    }
    if ($Stop) {
        Write-Host 'Stopping services on the server...'
        Invoke-RemoteServiceScript 'stop.sh' $StopArgs
        Write-Host 'Stop command completed.'
        return
    }

    if ($Connect) {
        Invoke-OpenSsh 'ssh.exe' ($taskCommon + @('-p', '22', $taskTarget))
        return
    }

    if ($SyncKey) {
        Sync-ServerTokens
        return
    }

    try {
        Invoke-OpenSsh 'scp.exe' ($taskCommon + @('-P', '22', $taskArchive, "${taskTarget}:dafeiyu-upload.tar.gz"))
        $taskRemoteCommand = 'set -eu; umask 077; mkdir -p "$HOME/dafeiyu"; tar -xzf "$HOME/dafeiyu-upload.tar.gz" -C "$HOME/dafeiyu"; chmod 600 "$HOME/dafeiyu/key.txt"; rm -f "$HOME/dafeiyu-upload.tar.gz"'
        Invoke-OpenSsh 'ssh.exe' ($taskCommon + @('-p', '22', $taskTarget, $taskRemoteCommand))
        Write-Host 'Upload complete. Starting deployment on Ubuntu; keep this window open.'
        $taskDeployCommand = 'cd "$HOME/dafeiyu" && if [ "$(id -u)" -eq 0 ]; then bash deploy.sh; else sudo -n bash deploy.sh; fi'
        Invoke-OpenSsh 'ssh.exe' ($taskCommon + @('-p', '22', $taskTarget, $taskDeployCommand)) 'Ubuntu deployment failed. Fix the error above, then rerun upload.ps1.'
        if ($taskHasQqFile) { Sync-QqPasswordFile $taskQqFile } else { Write-Host 'No QQ.txt found; skipping password fallback sync.' }
        try {
            Sync-ServerTokens
        } catch {
            Write-Warning '服务已部署完成，但把服务器 Token 写回本机 key.txt 失败：'
            Write-Warning $_.Exception.Message
            Write-Warning '这不会影响服务器运行。请关闭可能占用 key.txt 的程序或取消只读属性，然后运行 .\upload.ps1 -SyncKey 重试。'
        }
    } finally {
        if (Test-Path -LiteralPath $taskArchive) { Remove-Item -LiteralPath $taskArchive }
    }
    Write-Host 'Deployment complete. QQ login is left to you in NapCat WebUI.'
    Write-Host "AstrBot: http://${taskAddress}:6185/"
    Write-Host "NapCat:  http://${taskAddress}:6099/webui/web_login"
} finally {
    foreach ($taskFile in @($taskAskPass, $taskDownloaded, $taskArchive, $taskQqSecret)) {
        if ($taskKeepArchive -and $taskFile -eq $taskArchive) { continue }
        if (Test-Path -LiteralPath $taskFile -PathType Leaf) { Remove-Item -LiteralPath $taskFile }
    }
    if ((Get-ChildItem -LiteralPath $taskTemp -Force | Measure-Object).Count -eq 0) {
        Remove-Item -LiteralPath $taskTemp
    }
}
