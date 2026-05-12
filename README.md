# codex-memory

Config-driven Codex CLI memory tools.

`codex-memory` exports local Codex CLI sessions into project-local memory, rebuilds summary/index/facts files, supports fast text search across per-machine history, and can bootstrap a project with config and wrappers.

## Features

- project-local memory layout
- per-machine separation
- configurable storage roots and naming
- full rebuild export
- summary/raw/facts/index outputs
- search across one machine or all machines
- `init` command for config and wrappers
- Linux/macOS and Windows wrapper-friendly workflow

## Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
```

For Python 3.10, `tomli` is installed automatically.

## Commands

```bash
codex-memory init --project-root . --project-id my_project --project-name my_project
codex-memory export
codex-memory search "reranker"
codex-memory doctor
codex-memory config show
```

You can also run it as a module:

```bash
python3 -m codex_memory export
```

## Minimal config

Create `.codex-memory.toml` in a project root:

```toml
project_id = "my_project"
project_name = "my_project"

sessions_dir = "~/.codex/sessions"
preferred_storage_root = ".codex/memory"
fallback_storage_root = ".codex-sync/memory"
project_memory_dir_template = "{storage_root}/{project_id}/{machine}"
```

Optional local overrides that should stay out of git:

- `.codex-memory.local.toml`

## Typical workflow

Initialize a project once:

```bash
codex-memory init --project-root . --project-id my_project --project-name my_project
```

Then use:

```bash
codex-memory export
codex-memory search "baseline"
codex-memory search "reranker" --all-machines
```

## Output layout

By default memory is written into:

- `.codex/memory/<project_id>/<machine>/`

Fallback when `.codex/` is not writable:

- `.codex-sync/memory/<project_id>/<machine>/`

Typical contents:

- `INDEX.md`
- `FACTS.md`
- `summary/*.md`
- `raw/*.md`

`raw/` is usually better kept out of git.

## Tests

```bash
python3 -m unittest tests.test_codex_memory -v
```
