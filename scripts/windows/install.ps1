param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
$Prefix = 'C:\ProgramData\remote-fs-browser'
$Source = (Resolve-Path "$PSScriptRoot/../..").Path
function Checked { param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Installation failed: $Command" }
}
if (!(Get-Command choco -ErrorAction SilentlyContinue)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Installer = Join-Path $env:TEMP 'remote-fs-browser-choco.ps1'
    Invoke-WebRequest https://community.chocolatey.org/install.ps1 -OutFile $Installer
    & $Installer
    Remove-Item $Installer
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + $env:Path
Checked 'choco' @('install','python312','git','cmake','mingw','-y','--no-progress')
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + $env:Path
New-Item -ItemType Directory -Force $Prefix | Out-Null
Checked 'icacls' @($Prefix,'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F')
Checked 'python' @('-m','venv',"$Prefix/venv")
Checked "$Prefix/venv/Scripts/python.exe" @('-m','pip','install',$Source)
if (!(Test-Path "$Prefix/libnfs-src/.git")) { Checked 'git' @('clone','https://github.com/sahlberg/libnfs.git',"$Prefix/libnfs-src") }
$Revision = 'c69a48c8116fd50287875decd50474685937a4af'
Checked 'git' @('-C',"$Prefix/libnfs-src",'fetch','origin',$Revision)
Checked 'git' @('-C',"$Prefix/libnfs-src",'checkout','--detach',$Revision)
# Restrict upstream's GCC warning flag to C, not the Windows resource compiler.
$Checks = "$Prefix/libnfs-src/cmake/ConfigureChecks.cmake"
$Text = [IO.File]::ReadAllText($Checks).Replace('add_definitions(-Wall)', 'add_compile_options("$<$<COMPILE_LANGUAGE:C>:-Wall>")')
[IO.File]::WriteAllText($Checks, $Text)
Checked 'cmake' @('-S',"$Prefix/libnfs-src",'-B',"$Prefix/build",'-G','MinGW Makefiles','-DBUILD_SHARED_LIBS=ON','-DENABLE_TLS=OFF','-DENABLE_UTILS=OFF','-DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc')
Checked 'cmake' @('--build',"$Prefix/build",'--parallel','2')
$Dll = Get-ChildItem "$Prefix/build" -Recurse -Filter '*nfs*.dll' | Select-Object -First 1
if (!$Dll) { throw 'libnfs DLL was not built' }
Copy-Item $Dll.FullName "$Prefix/libnfs.dll" -Force
Copy-Item $Config "$Prefix/config.json" -Force
@"
`$env:LIBNFS_LIBRARY = '$Prefix/libnfs.dll'
& '$Prefix/venv/Scripts/remotefs.exe' serve --no-defaults --config '$Prefix/config.json'
exit `$LASTEXITCODE
"@ | Set-Content "$Prefix/start.ps1"
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Prefix/start.ps1`""
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'Remote filesystem browser' -Action $Action -Trigger $Trigger -Settings $Settings -User SYSTEM -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName 'Remote filesystem browser'
# No public firewall opening. Configure access for the control plane explicitly.
