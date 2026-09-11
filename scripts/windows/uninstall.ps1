param([switch]$Purge)
$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName 'Remote filesystem browser' -ErrorAction SilentlyContinue) {
  Stop-ScheduledTask -TaskName 'Remote filesystem browser'
  Unregister-ScheduledTask -TaskName 'Remote filesystem browser' -Confirm:$false
}
Remove-Item 'C:\ProgramData\remote-fs-browser\.deployment-success' -ErrorAction SilentlyContinue
if ($Purge) { Remove-Item 'C:\ProgramData\remote-fs-browser' -Recurse -Force }
