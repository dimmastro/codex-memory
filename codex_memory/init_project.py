from __future__ import annotations

import importlib.resources as resources
from pathlib import Path

from .config import MemoryConfig


def template_text(name: str) -> str:
    return resources.files("codex_memory").joinpath("templates", name).read_text(encoding="utf-8")


def render_default_config(config: MemoryConfig) -> str:
    template = template_text("default_config.toml")
    return template.replace("{project_id}", config.project_id).replace("{project_name}", config.project_name)


def render_wrapper(name: str, project_root: Path) -> str:
    template = template_text(name)
    return template.replace("{project_root}", project_root.as_posix())


def maybe_write(path: Path, content: str, force: bool) -> Path | None:
    if path.exists() and not force:
        return None
    path.write_text(content, encoding="utf-8")
    return path


def init_project(config: MemoryConfig, force: bool = False, wrapper_name: str = "run_codex") -> list[Path]:
    written: list[Path] = []
    project_root = config.project_root

    config_path = project_root / ".codex-memory.toml"
    result = maybe_write(config_path, render_default_config(config), force=force)
    if result is not None:
        written.append(result)

    wrappers = {
        f"{wrapper_name}.sh": render_wrapper("run_codex.sh", project_root),
        f"{wrapper_name}.cmd": render_wrapper("run_codex.cmd", project_root),
        f"{wrapper_name}.ps1": render_wrapper("run_codex.ps1", project_root),
    }
    for filename, content in wrappers.items():
        path = project_root / filename
        result = maybe_write(path, content, force=force)
        if result is not None:
            if path.suffix == ".sh":
                path.chmod(0o755)
            written.append(result)

    return written
