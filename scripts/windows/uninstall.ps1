param([switch]$Purge)
$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName 'Remote filesystem browser' -ErrorAction SilentlyContinue) {
  Stop-ScheduledTask -TaskName 'Remote filesystem browser'
  Unregister-ScheduledTask -TaskName 'Remote filesystem browser' -Confirm:$false
}
if ($Purge) { Remove-Item 'C:\ProgramData\remote-fs-browser' -Recurse -Force }
