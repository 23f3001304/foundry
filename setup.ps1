# Sets Foundry up. Run it as: powershell -ExecutionPolicy Bypass -File .\setup.ps1, with --try, --stop, --status or --reset on the end. This only finds uv. Everything else is in tools/foundry_setup.py.
# The Bypass is what lets this run under Windows' default policy. It applies only to that one run and changes no setting.
$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $guide = "https://docs.astral.sh/uv/getting-started/installation/"
    Write-Output "Foundry runs itself with uv, and uv is not on your PATH."
    if ([Console]::IsInputRedirected) {
        Write-Output "Install it from $guide and run this again."
        exit 1
    }
    Write-Output "Setup can install it: this fetches uv's official install script from https://astral.sh/uv/install.ps1 and runs it."
    Write-Output "That script puts uv in your own bin folder, and it may change your user PATH to add that folder."
    $answer = Read-Host "Install uv this way? [y/N]"
    if ($answer -notmatch "^[yY]") {
        Write-Output "Nothing was installed. Install uv from $guide and run this again."
        exit 1
    }
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Output "uv did not install. Check your internet connection, or install it from $guide, and run this again."
        exit 1
    }
    $env:Path = "$HOME\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Output "uv installed, but this terminal can't find it yet. Open a new terminal and run this again."
        exit 1
    }
}

& uv run --no-project --isolated --python ">=3.12" "$PSScriptRoot\tools\foundry_setup.py" @args
exit $LASTEXITCODE
