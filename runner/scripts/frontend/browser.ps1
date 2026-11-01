# Starts (or stops) the headed browser used for manual login, with remote
# debugging on the given port and a throwaway profile under the scratchpad.
# Uses the system Edge: Playwright's bundled Chromium fails its sandbox when
# the Windows user path has non-ASCII characters.
#   powershell -File browser.ps1 start <url> <scratchpad> [port]
#   powershell -File browser.ps1 stop  <scratchpad>
# Parallel runs stay apart: the port is the requested one or the next free one and is written to
# <scratchpad>\cdp.port; stop only kills the Edge on this scratchpad's profile and the recorder whose
# pid is in <scratchpad>\recorder.pid.
param(
  [Parameter(Mandatory)][ValidateSet('start', 'stop')][string]$Action,
  [string]$Url,
  [string]$Scratchpad,
  [int]$Port = 9222
)

function Get-AbsoluteDir([string]$Dir) {
  New-Item -ItemType Directory -Force -Path $Dir | Out-Null
  (Resolve-Path -LiteralPath $Dir).ProviderPath
}

function Test-PortBusy([int]$P) {
  $client = New-Object Net.Sockets.TcpClient
  try { $client.Connect('127.0.0.1', $P); $true } catch { $false } finally { $client.Close() }
}

if ($Action -eq 'stop') {
  $Scratchpad = Get-AbsoluteDir $Url
  $profileDir = Join-Path $Scratchpad 'pw-profile'
  Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileDir) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
  $pidFile = Join-Path $Scratchpad 'recorder.pid'
  if (Test-Path -LiteralPath $pidFile) {
    $recorderPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    Get-CimInstance Win32_Process -Filter "ProcessId=$recorderPid" | Where-Object { $_.CommandLine -like '*recorder.js*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep 2
  if (Test-Path -LiteralPath $profileDir) {
    # \\?\ prefix: Edge extension folders exceed MAX_PATH under the scratchpad.
    $full = (Resolve-Path -LiteralPath $profileDir).ProviderPath
    Remove-Item -LiteralPath "\\?\$full" -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath (Join-Path $Scratchpad 'cdp.port') -Force -ErrorAction SilentlyContinue
  "profile removed: $(-not (Test-Path -LiteralPath $profileDir))"
  return
}

$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge not found' }
$Scratchpad = Get-AbsoluteDir $Scratchpad
$last = $Port + 50
while ((Test-PortBusy $Port) -and $Port -le $last) { $Port++ }
if ($Port -gt $last) { throw "no free port up to $last" }
$profileDir = Join-Path $Scratchpad 'pw-profile'
Start-Process -FilePath $edge -ArgumentList "--remote-debugging-port=$Port", "--user-data-dir=`"$profileDir`"", '--no-first-run', $Url
Set-Content -LiteralPath (Join-Path $Scratchpad 'cdp.port') -Value $Port -NoNewline
"started $Url on port $Port"
