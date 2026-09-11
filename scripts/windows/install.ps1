param(
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$Username,
    [string]$PasswordFile,
    [switch]$WithoutNfs,
    [switch]$SkipDependencies,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (!$Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run in elevated PowerShell.' }
$Config = (Resolve-Path -LiteralPath $Config).Path
$BootstrapArgs = @()
if ($Username) { $BootstrapArgs += @('--username', $Username) }
if ($PasswordFile) { $BootstrapArgs += @('--password-file', (Resolve-Path -LiteralPath $PasswordFile).Path) }

$Prefix = 'C:\ProgramData\remote-fs-browser'
$Source = (Resolve-Path "$PSScriptRoot/../..").Path
function Checked { param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Installation failed: $Command" }
}
if (!$SkipDependencies) {
if (!(Get-Command choco -ErrorAction SilentlyContinue)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Installer = Join-Path $env:TEMP 'remote-fs-browser-choco.ps1'
    Invoke-WebRequest https://community.chocolatey.org/install.ps1 -OutFile $Installer
    & $Installer
    Remove-Item $Installer
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + $env:Path
$Packages = @('install','python312','-y','--no-progress')
if (!$WithoutNfs) { $Packages += @('git','cmake','mingw') }
Checked 'choco' $Packages
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + $env:Path
}
Checked $Python @('-c','import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"')
New-Item -ItemType Directory -Force $Prefix | Out-Null
Checked 'icacls' @($Prefix,'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F')
if (Test-Path "$Prefix/venv/Scripts/python.exe") {
    & "$Prefix/venv/Scripts/python.exe" "$Source/scripts/deployment.py" --config $Config --destination "$Prefix/config.json" @BootstrapArgs --check
    if ($LASTEXITCODE -notin @(0,2)) { throw 'Invalid deployment configuration' }
}
if (Get-ScheduledTask -TaskName 'Remote filesystem browser' -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName 'Remote filesystem browser'
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if ((Get-ScheduledTask -TaskName 'Remote filesystem browser').State -ne 'Running') { break }
        Start-Sleep -Seconds 1
    }
    if ((Get-ScheduledTask -TaskName 'Remote filesystem browser').State -eq 'Running') { throw 'Existing service did not stop' }
}
Checked $Python @('-m','venv',"$Prefix/venv")
Checked "$Prefix/venv/Scripts/python.exe" @('-m','pip','install','--upgrade',$Source)
Checked "$Prefix/venv/Scripts/python.exe" (@("$Source/scripts/deployment.py",'--config',$Config,'--destination',"$Prefix/config.json") + $BootstrapArgs)
if (!$WithoutNfs) {
if (!(Test-Path "$Prefix/libnfs-src/.git")) { Checked 'git' @('clone','https://github.com/sahlberg/libnfs.git',"$Prefix/libnfs-src") }
$Revision = 'c69a48c8116fd50287875decd50474685937a4af'
Checked 'git' @('-C',"$Prefix/libnfs-src",'fetch','origin',$Revision)
Checked 'git' @('-C',"$Prefix/libnfs-src",'checkout','--detach',$Revision)
# Restrict upstream's GCC warning flag to C, not the Windows resource compiler.
$Checks = "$Prefix/libnfs-src/cmake/ConfigureChecks.cmake"
$Text = [IO.File]::ReadAllText($Checks).Replace('add_definitions(-Wall)', 'add_compile_options("$<$<COMPILE_LANGUAGE:C>:-Wall>")')
[IO.File]::WriteAllText($Checks, $Text)
$Gcc = (Get-Command gcc).Source
Checked 'cmake' @('-S',"$Prefix/libnfs-src",'-B',"$Prefix/build",'-G','MinGW Makefiles',"-DCMAKE_C_COMPILER=$Gcc",'-DBUILD_SHARED_LIBS=ON','-DENABLE_TLS=OFF','-DENABLE_UTILS=OFF','-DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc')
Checked 'cmake' @('--build',"$Prefix/build",'--parallel','2')
$Dll = Get-ChildItem "$Prefix/build" -Recurse -Filter '*nfs*.dll' | Select-Object -First 1
if (!$Dll) { throw 'libnfs DLL was not built' }
Copy-Item $Dll.FullName "$Prefix/libnfs.dll" -Force
}
$Library = if ($WithoutNfs) { '' } else { "$Prefix/libnfs.dll" }
@"
`$env:LIBNFS_LIBRARY = '$Library'
& '$Prefix/venv/Scripts/remotefs.exe' serve --no-defaults --config '$Prefix/config.json' >> '$Prefix/service.log' 2>> '$Prefix/service-error.log'
exit `$LASTEXITCODE
"@ | Set-Content "$Prefix/start.ps1"
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Prefix/start.ps1`""
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'Remote filesystem browser' -Action $Action -Trigger $Trigger -Settings $Settings -User SYSTEM -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName 'Remote filesystem browser'
Checked "$Prefix/venv/Scripts/python.exe" @("$Source/scripts/deployment.py",'--config',"$Prefix/config.json",'--health-check')
# No public firewall opening. Configure access for the control plane explicitly.
