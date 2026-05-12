from __future__ import annotations

import argparse
import os
import re
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None


ENV_PREFIX = "CODEX_MEMORY_"


def sanitize_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_")
    return value or "unknown"


def nearest_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".codex-memory.toml").exists():
            return candidate
        if (candidate / ".git").exists():
            return candidate
        if (candidate / "AGENTS.md").exists():
            return candidate
    return start.resolve()


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return parse_simple_toml(text)


def parse_simple_value(raw: str) -> Any:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_simple_toml(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        index += 1
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, raw_value = [part.strip() for part in stripped.split("=", 1)]
        if raw_value == "[":
            items: list[Any] = []
            while index < len(lines):
                array_line = lines[index].strip()
                index += 1
                if not array_line or array_line.startswith("#"):
                    continue
                if array_line == "]":
                    break
                if array_line.endswith(","):
                    array_line = array_line[:-1].rstrip()
                items.append(parse_simple_value(array_line))
            parsed[key] = items
            continue
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            if not inner:
                parsed[key] = []
            else:
                parts = [part.strip() for part in inner.split(",") if part.strip()]
                parsed[key] = [parse_simple_value(part) for part in parts]
            continue
        parsed[key] = parse_simple_value(raw_value)
    return parsed


def expand_path(value: str | Path | None, *, project_root: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value).format(project_root=project_root)).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


@dataclass
class MemoryConfig:
    project_root: Path
    project_id: str
    project_name: str
    machine_name: str
    sessions_dir: Path
    preferred_storage_root: Path
    fallback_storage_root: Path
    storage_root: Path
    project_memory_dir_template: str
    raw_dir_name: str
    summary_dir_name: str
    include_raw: bool
    include_summary: bool
    include_facts: bool
    include_index: bool
    sanitize_missing_links: bool
    relative_paths: bool
    deduplicate_paths: bool
    ignore_path_only_messages: bool
    ignore_final_assistant_marker: bool
    ignore_commentary: bool
    raw_text_limit: int
    summary_user_limit: int
    summary_assistant_limit: int
    summary_command_limit: int
    summary_error_limit: int
    max_commands_per_exchange: int
    max_files_per_exchange: int
    max_errors_per_exchange: int
    max_commentary_items: int
    meaningful_assistant_prefix_blacklist: list[str]
    global_config_path: Path
    project_config_path: Path
    local_config_path: Path

    @property
    def project_memory_root(self) -> Path:
        return self.storage_root / self.project_id

    @property
    def target_dir(self) -> Path:
        return self.render_memory_path(self.machine_name)

    @property
    def raw_dir(self) -> Path:
        return self.target_dir / self.raw_dir_name

    @property
    def summary_dir(self) -> Path:
        return self.target_dir / self.summary_dir_name

    def render_memory_path(self, machine_name: str) -> Path:
        rendered = self.project_memory_dir_template.format(
            storage_root=self.storage_root.as_posix(),
            project_id=self.project_id,
            project_name=self.project_name,
            machine=machine_name,
            machine_name=machine_name,
        )
        path = Path(rendered)
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = value.as_posix()
        data["target_dir"] = self.target_dir.as_posix()
        data["raw_dir"] = self.raw_dir.as_posix()
        data["summary_dir"] = self.summary_dir.as_posix()
        data["project_memory_root"] = self.project_memory_root.as_posix()
        return data


DEFAULTS: dict[str, Any] = {
    "project_id": None,
    "project_name": None,
    "machine_name": sanitize_name(socket.gethostname() or "unknown"),
    "sessions_dir": "~/.codex/sessions",
    "preferred_storage_root": ".codex/memory",
    "fallback_storage_root": ".codex-sync/memory",
    "storage_root": None,
    "project_memory_dir_template": "{storage_root}/{project_id}/{machine}",
    "raw_dir_name": "raw",
    "summary_dir_name": "summary",
    "include_raw": True,
    "include_summary": True,
    "include_facts": True,
    "include_index": True,
    "sanitize_missing_links": True,
    "relative_paths": True,
    "deduplicate_paths": True,
    "ignore_path_only_messages": True,
    "ignore_final_assistant_marker": True,
    "ignore_commentary": False,
    "raw_text_limit": 4000,
    "summary_user_limit": 500,
    "summary_assistant_limit": 1400,
    "summary_command_limit": 180,
    "summary_error_limit": 180,
    "max_commands_per_exchange": 8,
    "max_files_per_exchange": 10,
    "max_errors_per_exchange": 5,
    "max_commentary_items": 20,
    "meaningful_assistant_prefix_blacklist": [
        "Сейчас ",
        "Проверю ",
        "Пересоберу ",
        "Жду ",
        "Исправлю ",
        "Добавлю ",
        "Нашёл ",
        "Причина ",
    ],
}

ENV_MAP: dict[str, tuple[str, str]] = {
    "PROJECT_ID": ("project_id", "str"),
    "PROJECT_NAME": ("project_name", "str"),
    "MACHINE": ("machine_name", "str"),
    "SESSIONS_DIR": ("sessions_dir", "path"),
    "PREFERRED_STORAGE_ROOT": ("preferred_storage_root", "path"),
    "FALLBACK_STORAGE_ROOT": ("fallback_storage_root", "path"),
    "STORAGE_ROOT": ("storage_root", "path"),
    "PROJECT_MEMORY_DIR_TEMPLATE": ("project_memory_dir_template", "str"),
    "RAW_TEXT_LIMIT": ("raw_text_limit", "int"),
    "SUMMARY_USER_LIMIT": ("summary_user_limit", "int"),
    "SUMMARY_ASSISTANT_LIMIT": ("summary_assistant_limit", "int"),
    "SUMMARY_COMMAND_LIMIT": ("summary_command_limit", "int"),
    "SUMMARY_ERROR_LIMIT": ("summary_error_limit", "int"),
}


def parse_env(project_root: Path) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for env_name, (field_name, kind) in ENV_MAP.items():
        raw = os.environ.get(f"{ENV_PREFIX}{env_name}")
        if raw in (None, ""):
            continue
        if kind == "int":
            parsed[field_name] = int(raw)
        elif kind == "path":
            parsed[field_name] = expand_path(raw, project_root=project_root)
        else:
            parsed[field_name] = raw
    return parsed


def cli_overrides(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for field_name in (
        "project_id",
        "project_name",
        "machine_name",
        "project_memory_dir_template",
    ):
        value = getattr(args, field_name, None)
        if value not in (None, ""):
            mapping[field_name] = value
    for field_name in ("sessions_dir", "preferred_storage_root", "fallback_storage_root", "storage_root"):
        value = getattr(args, field_name, None)
        if value not in (None, ""):
            mapping[field_name] = expand_path(value, project_root=project_root)
    for field_name in (
        "raw_text_limit",
        "summary_user_limit",
        "summary_assistant_limit",
        "summary_command_limit",
        "summary_error_limit",
        "max_commands_per_exchange",
        "max_files_per_exchange",
        "max_errors_per_exchange",
        "max_commentary_items",
    ):
        value = getattr(args, field_name, None)
        if value is not None:
            mapping[field_name] = value
    return mapping


def choose_storage_root(explicit: Path | None, preferred: Path, fallback: Path) -> Path:
    if explicit is not None:
        return explicit
    if os.access(preferred.parent, os.W_OK):
        return preferred
    return fallback


def load_config(args: argparse.Namespace | None = None) -> MemoryConfig:
    args = args or argparse.Namespace()
    project_root_arg = getattr(args, "project_root", None)
    start = Path(project_root_arg).expanduser().resolve() if project_root_arg else Path.cwd()
    project_root = nearest_project_root(start)

    global_config_path = Path.home() / ".config" / "codex-memory" / "config.toml"
    project_config_path = project_root / ".codex-memory.toml"
    local_config_path = project_root / ".codex-memory.local.toml"

    merged = dict(DEFAULTS)
    for source in (
        read_toml(global_config_path),
        read_toml(project_config_path),
        read_toml(local_config_path),
        parse_env(project_root),
        cli_overrides(args, project_root),
    ):
        merged.update({key: value for key, value in source.items() if value is not None})

    project_name = str(merged.get("project_name") or project_root.name)
    project_id = sanitize_name(str(merged.get("project_id") or project_name))
    machine_name = sanitize_name(str(merged.get("machine_name") or DEFAULTS["machine_name"]))

    preferred_storage_root = expand_path(merged["preferred_storage_root"], project_root=project_root)
    fallback_storage_root = expand_path(merged["fallback_storage_root"], project_root=project_root)
    explicit_storage_root = merged.get("storage_root")
    if isinstance(explicit_storage_root, (str, Path)):
        explicit_storage_root = expand_path(explicit_storage_root, project_root=project_root)
    storage_root = choose_storage_root(explicit_storage_root, preferred_storage_root, fallback_storage_root)

    sessions_dir = expand_path(merged["sessions_dir"], project_root=project_root)
    if sessions_dir is None or preferred_storage_root is None or fallback_storage_root is None or storage_root is None:
        raise RuntimeError("failed to resolve memory paths")

    return MemoryConfig(
        project_root=project_root,
        project_id=project_id,
        project_name=project_name,
        machine_name=machine_name,
        sessions_dir=sessions_dir,
        preferred_storage_root=preferred_storage_root,
        fallback_storage_root=fallback_storage_root,
        storage_root=storage_root,
        project_memory_dir_template=str(merged["project_memory_dir_template"]),
        raw_dir_name=str(merged["raw_dir_name"]),
        summary_dir_name=str(merged["summary_dir_name"]),
        include_raw=bool(merged["include_raw"]),
        include_summary=bool(merged["include_summary"]),
        include_facts=bool(merged["include_facts"]),
        include_index=bool(merged["include_index"]),
        sanitize_missing_links=bool(merged["sanitize_missing_links"]),
        relative_paths=bool(merged["relative_paths"]),
        deduplicate_paths=bool(merged["deduplicate_paths"]),
        ignore_path_only_messages=bool(merged["ignore_path_only_messages"]),
        ignore_final_assistant_marker=bool(merged["ignore_final_assistant_marker"]),
        ignore_commentary=bool(merged["ignore_commentary"]),
        raw_text_limit=int(merged["raw_text_limit"]),
        summary_user_limit=int(merged["summary_user_limit"]),
        summary_assistant_limit=int(merged["summary_assistant_limit"]),
        summary_command_limit=int(merged["summary_command_limit"]),
        summary_error_limit=int(merged["summary_error_limit"]),
        max_commands_per_exchange=int(merged["max_commands_per_exchange"]),
        max_files_per_exchange=int(merged["max_files_per_exchange"]),
        max_errors_per_exchange=int(merged["max_errors_per_exchange"]),
        max_commentary_items=int(merged["max_commentary_items"]),
        meaningful_assistant_prefix_blacklist=[
            str(item) for item in merged["meaningful_assistant_prefix_blacklist"]
        ],
        global_config_path=global_config_path,
        project_config_path=project_config_path,
        local_config_path=local_config_path,
    )


def dump_config(config: MemoryConfig) -> str:
    data = config.as_dict()
    lines: list[str] = []
    for key in sorted(data):
        value = data[key]
        if isinstance(value, list):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f"{key} = {value}")
    return "\n".join(lines)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", help="explicit project root")
    parser.add_argument("--project-id", help="stable project id")
    parser.add_argument("--project-name", help="display project name")
    parser.add_argument("--machine-name", help="override machine name")
    parser.add_argument("--sessions-dir", help="Codex sessions directory")
    parser.add_argument("--preferred-storage-root", help="preferred storage root")
    parser.add_argument("--fallback-storage-root", help="fallback storage root")
    parser.add_argument("--storage-root", help="force storage root")
    parser.add_argument(
        "--project-memory-dir-template",
        help="template like {storage_root}/{project_id}/{machine}",
    )
    parser.add_argument("--raw-text-limit", type=int, help="raw text truncation limit")
    parser.add_argument("--summary-user-limit", type=int, help="summary user truncation limit")
    parser.add_argument("--summary-assistant-limit", type=int, help="summary assistant truncation limit")
    parser.add_argument("--summary-command-limit", type=int, help="summary command truncation limit")
    parser.add_argument("--summary-error-limit", type=int, help="summary error truncation limit")
    parser.add_argument("--max-commands-per-exchange", type=int, help="max commands per exchange")
    parser.add_argument("--max-files-per-exchange", type=int, help="max files per exchange")
    parser.add_argument("--max-errors-per-exchange", type=int, help="max errors per exchange")
    parser.add_argument("--max-commentary-items", type=int, help="max commentary items")


def ensure_python_version() -> None:
    return None
