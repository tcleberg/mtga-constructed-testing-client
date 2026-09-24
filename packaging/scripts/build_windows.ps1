$ErrorActionPreference = "Stop"
$Version = if ($env:APP_VERSION) { $env:APP_VERSION } else { "0.3.2" }

Remove-Item -Recurse -Force build, dist, artifacts -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force artifacts | Out-Null

python -m PyInstaller --clean --noconfirm packaging/pyinstaller/client.spec

# The executable is windowed, so it detaches unless we wait for it explicitly.
$SelfTest = Start-Process -FilePath ".\dist\MTGA Constructed Testing\MTGA Constructed Testing.exe" `
  -ArgumentList "--self-test" -Wait -PassThru
if ($SelfTest.ExitCode -ne 0) {
  throw "Packaged self-test failed with exit code $($SelfTest.ExitCode)"
}

if ($env:WINDOWS_CERT_PFX -and $env:WINDOWS_CERT_PASSWORD) {
  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    /f $env:WINDOWS_CERT_PFX /p $env:WINDOWS_CERT_PASSWORD `
    ".\dist\MTGA Constructed Testing\MTGA Constructed Testing.exe"
}

$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { $Iscc = "${env:ProgramFiles}\Inno Setup 6\ISCC.exe" }
& $Iscc "/DAppVersion=$Version" packaging/windows/installer.iss

$Setup = "artifacts\MTGA-Constructed-Testing-$Version-windows-x64-setup.exe"
if ($env:WINDOWS_CERT_PFX -and $env:WINDOWS_CERT_PASSWORD) {
  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    /f $env:WINDOWS_CERT_PFX /p $env:WINDOWS_CERT_PASSWORD $Setup
}
Get-FileHash $Setup -Algorithm SHA256 | ForEach-Object {
  "$($_.Hash.ToLower())  $(Split-Path $_.Path -Leaf)"
} | Set-Content artifacts\SHA256SUMS-windows-x64.txt
