$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
py -3 -m codex_memory export --project-root $Root
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& codex @args
exit $LASTEXITCODE
