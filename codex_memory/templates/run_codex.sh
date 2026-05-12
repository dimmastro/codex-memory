#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 -m codex_memory export --project-root "$ROOT"
exec codex "$@"
