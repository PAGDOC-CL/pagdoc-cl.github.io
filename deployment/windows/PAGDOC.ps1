# Run from Windows PowerShell. All application data stays inside the selected WSL distribution.
param(
    [ValidateSet('Check','Install','Start','Stop','Status','Provision','TrustCertificate')]
    [string]$Action = 'Check',
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$Distribution = 'Ubuntu'
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Install WSL first in administrator PowerShell: wsl --install -d Ubuntu. Restart and initialize Ubuntu.'
}
$distros = ((& wsl.exe --list --quiet) -join "`n").Replace([string][char]0, '')
if ($LASTEXITCODE -ne 0 -or ($distros -split "`n" | ForEach-Object { $_.Trim() }) -notcontains $Distribution) {
    throw "Initialize the selected Ubuntu distribution first: wsl --install -d $Distribution"
}
function Invoke-Ubuntu([string]$Command) {
    & wsl.exe -d $Distribution -- bash -lc $Command
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu command failed. Review the message above before continuing.' }
}
if ($Action -eq 'Install') {
    $install = @'
set -euo pipefail
sudo apt-get update
sudo apt-get install -y git python3 ca-certificates curl
target="$HOME/pagdoc-private"
if [[ -e "$target" ]]; then
  [[ -d "$target/.git" ]] || { echo 'Target exists and is not a repository.' >&2; exit 1; }
  [[ "$(git -C "$target" remote get-url origin)" == 'https://github.com/PAGDOC-CL/pagdoc-cl.github.io.git' ]] || { echo 'Unexpected existing repository.' >&2; exit 1; }
  echo 'Existing checkout retained; no automatic update or reset.'
else
  git clone --depth 1 https://github.com/PAGDOC-CL/pagdoc-cl.github.io.git "$target"
fi
cd "$target"
bash deployment/local/install-engine.sh
'@
    Invoke-Ubuntu $install
} elseif ($Action -eq 'TrustCertificate') {
    $certificate = & wsl.exe -d $Distribution -- bash -lc 'cd "$HOME/pagdoc-private" && bash deployment/local/control.sh certificate'
    if ($LASTEXITCODE -ne 0 -or ($certificate -join "`n") -notmatch '-----BEGIN CERTIFICATE-----') { throw 'Start PAGDOC first; the local certificate is not available.' }
    $file = Join-Path $env:TEMP ('pagdoc-local-' + [guid]::NewGuid().ToString() + '.crt')
    try {
        [IO.File]::WriteAllText($file, (($certificate -join "`n") + "`n"), [Text.Encoding]::ASCII)
        $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($file)
        Write-Host ('Trusting the PAGDOC local CA for this Windows user. Thumbprint: ' + $cert.Thumbprint)
        Import-Certificate -FilePath $file -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    } finally { Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue }
} else {
    $allowed = @{ Check='check'; Start='start'; Stop='stop'; Status='status'; Provision='provision' }
    Invoke-Ubuntu ('cd "$HOME/pagdoc-private" && bash deployment/local/control.sh ' + $allowed[$Action])
}
