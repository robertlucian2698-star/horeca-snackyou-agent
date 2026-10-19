"""Read Windows shortcut/uninstall metadata without executing targets."""
import os,json,subprocess
from pathlib import Path
SCRIPT = r'''[Console]::OutputEncoding=[Text.Encoding]::UTF8
$ErrorActionPreference='SilentlyContinue'
$paths=@()
$shell=New-Object -ComObject WScript.Shell
$roots=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('CommonDesktopDirectory'),[Environment]::GetFolderPath('StartMenu'),[Environment]::GetFolderPath('CommonStartMenu'))
foreach($root in $roots){
 Get-ChildItem -LiteralPath $root -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | Select-Object -First 300 | ForEach-Object {
  $link=$shell.CreateShortcut($_.FullName)
  if($_.Name -match 'Unity' -or $link.TargetPath -match 'UnityPOS'){
   if($link.TargetPath){$paths+=Split-Path -Parent $link.TargetPath}
   if($link.WorkingDirectory){$paths+=$link.WorkingDirectory}
  }
 }
}
$keys=@('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
foreach($key in $keys){Get-ItemProperty $key | Where-Object {$_.DisplayName -match 'UnityPOS'} | ForEach-Object {if($_.InstallLocation){$paths+=$_.InstallLocation}}}
@($paths | Select-Object -Unique -First 12) | ConvertTo-Json -Compress'''
def installed_pos_folders():
 if os.name!='nt': return []
 try:
  ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
  result=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-Command',SCRIPT],capture_output=True,timeout=20,encoding='utf-8',errors='replace')
  data=json.loads(result.stdout.strip().lstrip('\ufeff') or '[]')
  if isinstance(data,str): data=[data]
  return [Path(p) for p in data if isinstance(p,str) and p][:12]
 except Exception: return []
