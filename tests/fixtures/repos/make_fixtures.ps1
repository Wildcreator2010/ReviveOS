# Regenerate the golden fixture repositories.
# Set REVIVE_GIT_BIN to point at a git executable when git is not on PATH.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $env:REVIVE_GIT_BIN) {
  $candidate = Join-Path $here "..\..\..\.tools\git\cmd\git.exe"
  if (Test-Path $candidate) { $env:REVIVE_GIT_BIN = (Resolve-Path $candidate).Path }
}
& python (Join-Path $here "make_fixtures.py") @args
exit $LASTEXITCODE
