# Sets Foundry up: .\setup.ps1, or .\setup.ps1 --try, --stop, --status, --reset. This only finds uv. Everything else is in tools/foundry_setup.py.
# If Windows says running scripts is disabled: powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Output "Foundry runs itself with uv, and uv is not on your PATH."
    if ([Console]::IsInputRedirected) {
        Write-Output "Install it from https://docs.astral.sh/uv/getting-started/installation/ and run this again."
        exit 1
    }
    $answer = Read-Host "Install uv now with its official installer from https://astral.sh/uv? [y/N]"
    if ($answer -notmatch "^[yY]") {
        Write-Output "Nothing was installed. Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run this again."
        exit 1
    }
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$HOME\.local\bin;$env:Path"
}

& uv run --no-project --isolated --quiet --python ">=3.12" "$PSScriptRoot\tools\foundry_setup.py" @args
exit $LASTEXITCODE
