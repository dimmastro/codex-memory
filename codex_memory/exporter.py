from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import MemoryConfig


@dataclass
class Event:
    timestamp: str
    kind: str
    role: str
    text: str
    name: str = ""
    command: str = ""
    exit_code: int | None = None


@dataclass
class SessionExport:
    source: Path
    updated: dt.datetime
    title: str
    meta: dict[str, Any]
    events: list[Event]
    files_changed: list[str]
    commands: list[str]
    errors: list[str]
    raw_path: Path
    summary_path: Path


@dataclass
class Exchange:
    user_text: str
    assistant_text: str
    files_changed: list[str]
    commands: list[str]
    errors: list[str]


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_")
    return value[:120] or "session"


def cleanup_target(config: MemoryConfig) -> None:
    if config.target_dir.exists():
        shutil.rmtree(config.target_dir)
    if config.include_raw:
        config.raw_dir.mkdir(parents=True, exist_ok=True)
    if config.include_summary:
        config.summary_dir.mkdir(parents=True, exist_ok=True)
    if not config.include_raw and not config.include_summary:
        config.target_dir.mkdir(parents=True, exist_ok=True)


def iter_session_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    files = [path for path in base.rglob("*") if path.is_file() and path.suffix.lower() in {".jsonl", ".json"}]
    return sorted(files, key=lambda path: path.stat().st_mtime)


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (extract_text(item) for item in value) if part)
    if isinstance(value, dict):
        if "payload" in value:
            text = extract_text(value["payload"])
            if text:
                return text
        if "content" in value:
            text = extract_text(value["content"])
            if text:
                return text
        for key in ("text", "message", "output", "final", "response"):
            if key in value:
                text = extract_text(value[key])
                if text:
                    return text
        return ""
    return str(value)


def session_is_relevant(meta: dict[str, Any], config: MemoryConfig) -> bool:
    cwd = str(meta.get("cwd") or "")
    repo_url = str((meta.get("git") or {}).get("repository_url") or "")
    root_resolved = config.project_root.as_posix().lower()
    project_id = config.project_id.lower()
    project_name = config.project_name.lower()

    if cwd:
        try:
            resolved = Path(cwd).expanduser().resolve().as_posix().lower()
        except Exception:
            resolved = cwd.lower()
        if resolved.startswith(root_resolved):
            return True
        if project_id in resolved or project_name in resolved:
            return True
    if repo_url and (project_id in repo_url.lower() or project_name in repo_url.lower()):
        return True
    return False


def truncate(text: str, limit: int) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit].rstrip()}\n\n[truncated {len(stripped) - limit} chars]"


def sanitize_local_links(text: str, config: MemoryConfig) -> str:
    if not config.sanitize_missing_links:
        return text
    pattern = re.compile(r"\[([^\]]+)\]\((/home/[^)]+)\)")

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2)
        if Path(target).exists():
            return match.group(0)
        return f"`{label}` (missing: `{target}`)"

    return pattern.sub(replace, text)


def is_meaningful_assistant_text(text: str, config: MemoryConfig) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return not any(stripped.startswith(prefix) for prefix in config.meaningful_assistant_prefix_blacklist)


def is_meaningful_user_text(text: str, config: MemoryConfig) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "<environment_context>" in stripped:
        return False
    if config.ignore_final_assistant_marker and stripped == "## Final assistant message":
        return False
    if config.ignore_path_only_messages and stripped.startswith("/home/") and "\n" not in stripped and len(stripped) < 260:
        return False
    return True


def normalize_file_path(text_path: str, config: MemoryConfig) -> str:
    normalized = text_path.replace("file://", "").strip("`")
    if not config.relative_paths:
        return normalized
    try:
        path = Path(normalized)
        if path.is_absolute():
            return path.resolve().relative_to(config.project_root).as_posix()
    except Exception:
        return normalized
    return normalized


def files_from_text(text: str, config: MemoryConfig) -> list[str]:
    found: list[str] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if collecting:
                break
            continue
        if stripped == "Updated the following files:":
            collecting = True
            continue
        if collecting:
            match = re.match(r"^[AMDRCU?]{1,2}\s+(.+)$", stripped)
            if match:
                found.append(match.group(1).strip())
                continue
            break

    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^[AMDRCU?]{1,2}\s+(.+\.(?:py|md|txt|json|toml|yaml|yml|sh|ini|cfg|csv|ps1|cmd))$", stripped)
        if match:
            found.append(match.group(1).strip())

    unique: list[str] = []
    seen: set[str] = set()
    for item in found:
        normalized = normalize_file_path(item, config)
        if not config.deduplicate_paths or normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def normalize_error_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if "traceback" in lowered:
            return "Traceback"
        if lowered.startswith("fatal:") or "exception" in lowered:
            return stripped[:240]
    return text.strip().splitlines()[0][:240] if text.strip() else ""


def extract_command_text(name: str, arguments: str) -> str:
    try:
        parsed = json.loads(arguments) if arguments else {}
    except Exception:
        return arguments.strip()
    if name == "exec_command":
        return str(parsed.get("cmd") or "").strip()
    if name == "shell":
        command = parsed.get("command")
        if isinstance(command, list):
            return " ".join(str(part) for part in command)
        return str(command or "").strip()
    return ""


def extract_output_text(output: Any) -> tuple[str, int | None]:
    if output is None:
        return "", None
    if isinstance(output, dict):
        metadata = output.get("metadata")
        exit_code = None
        if isinstance(metadata, dict) and isinstance(metadata.get("exit_code"), int):
            exit_code = metadata["exit_code"]
        text = extract_text(output.get("output") or output.get("stdout") or output.get("text") or output)
        return text, exit_code
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except Exception:
            return output, None
        return extract_output_text(parsed)
    return str(output), None


def parse_session(file_path: Path) -> tuple[dict[str, Any], list[Event]]:
    meta: dict[str, Any] = {}
    events: list[Event] = []
    raw = file_path.read_text(encoding="utf-8", errors="ignore")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue

        timestamp = str(parsed.get("timestamp") or "")
        kind = str(parsed.get("type") or "")
        payload = parsed.get("payload") if isinstance(parsed, dict) else None

        if kind == "session_meta" and isinstance(payload, dict):
            meta = payload
            continue
        if kind == "response_item" and isinstance(payload, dict):
            payload_type = str(payload.get("type") or "")
            if payload_type == "message":
                role = str(payload.get("role") or "message")
                text = extract_text(payload.get("content"))
                if text.strip() and role in {"user", "assistant"}:
                    events.append(Event(timestamp=timestamp, kind="message", role=role, text=text.strip()))
                continue
            if payload_type == "function_call":
                name = str(payload.get("name") or "")
                command = extract_command_text(name, str(payload.get("arguments") or ""))
                if command:
                    events.append(Event(timestamp=timestamp, kind="tool_call", role="tool_call", text=command, name=name, command=command))
                continue
            if payload_type in {"function_call_output", "custom_tool_call_output"}:
                text, exit_code = extract_output_text(payload.get("output"))
                if text.strip():
                    events.append(Event(timestamp=timestamp, kind="tool_output", role="tool_output", text=text.strip(), name=payload_type, exit_code=exit_code))
                continue
        if kind == "event_msg" and isinstance(payload, dict) and str(payload.get("type") or "") == "agent_reasoning":
            text = str(payload.get("text") or "").strip()
            if text:
                events.append(Event(timestamp=timestamp, kind="commentary", role="assistant / commentary", text=text))
    return meta, events


def first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("<environment_context>"):
            continue
        if re.fullmatch(r"<[^>]+>.*</[^>]+>", line):
            continue
        if line.startswith(("<cwd>", "<shell>", "<current_date>", "<timezone>")):
            continue
        if line.startswith("</"):
            continue
        if line.startswith("## Open tabs:"):
            continue
        if line.startswith("# Context from my IDE setup:"):
            continue
        if line.lower().startswith("я проверю актуальные"):
            continue
        if line.startswith("/home/") and " " not in line:
            continue
        return line
    return ""


def title_from_events(events: list[Event], source: Path) -> str:
    for event in events:
        if event.role != "user":
            continue
        title = first_meaningful_line(event.text)
        if title:
            return title[:160]
    return source.stem


def build_exchanges(events: list[Event], config: MemoryConfig) -> list[Exchange]:
    exchanges: list[Exchange] = []
    pending_user: str | None = None
    pending_assistant: str | None = None
    pending_commands: list[str] = []
    pending_files: list[str] = []
    pending_errors: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_user, pending_assistant, pending_commands, pending_files, pending_errors
        if not pending_user:
            return
        exchanges.append(
            Exchange(
                user_text=pending_user,
                assistant_text=(pending_assistant or "").strip(),
                files_changed=list(dict.fromkeys(pending_files)),
                commands=list(dict.fromkeys(pending_commands)),
                errors=list(dict.fromkeys(pending_errors)),
            )
        )
        pending_user = None
        pending_assistant = None
        pending_commands = []
        pending_files = []
        pending_errors = []

    for event in events:
        if event.role == "user" and is_meaningful_user_text(event.text, config):
            flush_pending()
            pending_user = event.text.strip()
            pending_assistant = None
            pending_commands = []
            pending_files = []
            pending_errors = []
            continue
        if pending_user and event.kind == "tool_call" and event.command:
            pending_commands.append(event.command)
            continue
        if pending_user and event.kind == "tool_output":
            pending_files.extend(files_from_text(event.text, config))
            if event.exit_code not in (None, 0):
                error_line = normalize_error_line(event.text)
                if error_line:
                    pending_errors.append(f"exit_code={event.exit_code}: {error_line}")
            elif re.search(r"\b(traceback)\b", event.text, flags=re.IGNORECASE):
                error_line = normalize_error_line(event.text)
                if error_line:
                    pending_errors.append(error_line)
            continue
        if event.role == "assistant" and pending_user:
            assistant_text = event.text.strip()
            if is_meaningful_assistant_text(assistant_text, config) and not pending_assistant:
                pending_assistant = assistant_text

    flush_pending()
    return exchanges


def summarize_session(source: Path, meta: dict[str, Any], events: list[Event], config: MemoryConfig) -> SessionExport:
    updated = dt.datetime.fromtimestamp(source.stat().st_mtime)
    title = title_from_events(events, source)
    files_changed: list[str] = []
    commands: list[str] = []
    errors: list[str] = []
    for event in events:
        if event.kind == "tool_call" and event.command:
            commands.append(event.command)
        if event.kind == "tool_output":
            files_changed.extend(files_from_text(event.text, config))
            if event.exit_code not in (None, 0):
                error_line = normalize_error_line(event.text)
                if error_line:
                    errors.append(f"exit_code={event.exit_code}: {error_line}")
            elif re.search(r"\b(traceback)\b", event.text, flags=re.IGNORECASE):
                error_line = normalize_error_line(event.text)
                if error_line:
                    errors.append(error_line)

    files_changed = list(dict.fromkeys(files_changed))
    commands = list(dict.fromkeys(command for command in commands if command))
    errors = list(dict.fromkeys(error for error in errors if error))

    base_name = f"{updated:%Y-%m-%d_%H-%M-%S}__{safe_name(source.stem)}.md"
    return SessionExport(
        source=source,
        updated=updated,
        title=title,
        meta=meta,
        events=events,
        files_changed=files_changed,
        commands=commands,
        errors=errors,
        raw_path=config.raw_dir / base_name,
        summary_path=config.summary_dir / base_name,
    )


def render_raw(session: SessionExport, config: MemoryConfig) -> str:
    lines = [
        f"# Raw Codex dialog: {session.source.stem}\n\n",
        f"- Source: `{session.source}`\n",
        f"- Updated: {session.updated.isoformat(timespec='seconds')}\n",
        f"- CWD: `{session.meta.get('cwd', '')}`\n",
        f"- Title: {session.title}\n\n",
    ]
    counter = 0
    for event in session.events:
        if event.kind == "tool_output":
            text = truncate(event.text, config.raw_text_limit)
        else:
            text = event.text.strip()
        if not text:
            continue
        counter += 1
        stamp = f" [{event.timestamp}]" if event.timestamp else ""
        header = event.role
        if event.kind == "tool_call" and event.name:
            header = f"{event.role} `{event.name}`"
        if event.kind == "tool_output" and event.exit_code is not None:
            header = f"{event.role} exit={event.exit_code}"
        lines.append(f"## {counter}. {header}{stamp}\n\n{text}\n\n")
    return "".join(lines)


def render_summary(session: SessionExport, config: MemoryConfig) -> str:
    user_messages = [event for event in session.events if event.role == "user" and is_meaningful_user_text(event.text, config)]
    assistant_messages = [event for event in session.events if event.role == "assistant"]
    commentary_messages = [] if config.ignore_commentary else [event for event in session.events if event.role == "assistant / commentary"]
    last_assistant = assistant_messages[-1].text.strip() if assistant_messages else ""
    exchanges = build_exchanges(session.events, config)

    lines = [
        f"# Session summary: {session.title}\n\n",
        f"- Source: `{session.source}`\n",
        f"- Updated: {session.updated.isoformat(timespec='seconds')}\n",
        f"- CWD: `{session.meta.get('cwd', '')}`\n",
        f"- User messages: {len(user_messages)}\n",
        f"- Assistant messages: {len(assistant_messages)}\n",
        f"- Commentary messages: {len(commentary_messages)}\n",
        f"- Files changed: {len(session.files_changed)}\n",
        f"- Commands captured: {len(session.commands)}\n",
        f"- Errors captured: {len(session.errors)}\n\n",
    ]

    if user_messages:
        lines.append("## User requests\n\n")
        for idx, event in enumerate(user_messages, start=1):
            lines.append(f"{idx}. {truncate(first_meaningful_line(event.text) or event.text, config.summary_user_limit)}\n")
        lines.append("\n")

    if exchanges:
        lines.append("## User -> assistant\n\n")
        for idx, exchange in enumerate(exchanges, start=1):
            user_text = truncate(first_meaningful_line(exchange.user_text) or exchange.user_text, config.summary_user_limit)
            assistant_text = truncate(sanitize_local_links(exchange.assistant_text, config), config.summary_assistant_limit)
            lines.append(f"### {idx}. User\n\n{user_text}\n\n")
            if assistant_text:
                lines.append(f"### Assistant\n\n{assistant_text}\n\n")
            if exchange.files_changed:
                lines.append("Files:\n")
                for path in exchange.files_changed[: config.max_files_per_exchange]:
                    lines.append(f"- `{path}`\n")
                lines.append("\n")
            if exchange.commands:
                lines.append("Commands:\n")
                for command in exchange.commands[: config.max_commands_per_exchange]:
                    lines.append(f"- `{truncate(command, config.summary_command_limit)}`\n")
                lines.append("\n")
            if exchange.errors:
                lines.append("Errors:\n")
                for error in exchange.errors[: config.max_errors_per_exchange]:
                    lines.append(f"- `{truncate(error, config.summary_error_limit)}`\n")
                lines.append("\n")

    if last_assistant:
        lines.append(f"## Final assistant message\n\n{truncate(sanitize_local_links(last_assistant, config), 2500)}\n\n")

    lines.append("## Session digest\n\n")
    if session.files_changed:
        lines.append("Files changed:\n")
        for path in session.files_changed[: config.max_files_per_exchange]:
            lines.append(f"- `{path}`\n")
    if session.commands:
        lines.append("Commands captured:\n")
        for command in session.commands[: config.max_commands_per_exchange]:
            lines.append(f"- `{truncate(command, config.summary_command_limit)}`\n")
    if session.errors:
        lines.append("Errors:\n")
        for error in session.errors[: config.max_errors_per_exchange]:
            lines.append(f"- `{error}`\n")
    if not session.files_changed and not session.commands and not session.errors:
        lines.append("- No technical artifacts captured.\n")
    lines.append("\n")

    if commentary_messages:
        lines.append("## Commentary checkpoints\n\n")
        for event in commentary_messages[: config.max_commentary_items]:
            lines.append(f"- {truncate(event.text, 240)}\n")
        lines.append("\n")

    lines.append(f"## Related files\n\n- [raw/{session.raw_path.name}](../raw/{session.raw_path.name})\n")
    return "".join(lines)


def render_index(sessions: list[SessionExport], config: MemoryConfig) -> str:
    lines = [
        f"# Codex memory index: {config.project_name}\n\n",
        f"Project id: `{config.project_id}`\n",
        f"Machine: `{config.machine_name}`\n",
        f"Root: `{config.target_dir}`\n\n",
        f"Rebuilt: {dt.datetime.now().isoformat(timespec='seconds')}\n\n",
        "| Updated | Title | Files | Errors | Summary |\n",
        "| --- | --- | ---: | ---: | --- |\n",
    ]
    for session in sorted(sessions, key=lambda item: item.updated, reverse=True):
        label = session.title.replace("|", "/")
        summary_rel = f"{config.summary_dir_name}/{session.summary_path.name}"
        lines.append(
            f"| {session.updated:%Y-%m-%d %H:%M} | {label[:80]} | {len(session.files_changed)} | {len(session.errors)} | [{session.summary_path.name}]({summary_rel}) |\n"
        )
    return "".join(lines)


def render_facts(sessions: list[SessionExport], config: MemoryConfig) -> str:
    file_counts: dict[str, int] = {}
    command_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    for session in sessions:
        for path in session.files_changed:
            file_counts[path] = file_counts.get(path, 0) + 1
        for command in session.commands:
            prefix = command.split()[0] if command.split() else command
            command_counts[prefix] = command_counts.get(prefix, 0) + 1
        for error in session.errors:
            error_counts[error] = error_counts.get(error, 0) + 1
    lines = [
        f"# Project facts: {config.project_name}\n\n",
        f"Project id: `{config.project_id}`\n",
        f"Machine: `{config.machine_name}`\n\n",
        f"Sessions: {len(sessions)}\n\n",
        "## Frequently changed files\n\n",
    ]
    for path, count in sorted(file_counts.items(), key=lambda item: (-item[1], item[0]))[:50]:
        lines.append(f"- {count}x `{path}`\n")
    lines.append("\n## Command prefixes\n\n")
    for prefix, count in sorted(command_counts.items(), key=lambda item: (-item[1], item[0]))[:30]:
        lines.append(f"- {count}x `{prefix}`\n")
    lines.append("\n## Errors seen\n\n")
    if error_counts:
        for error, count in sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))[:30]:
            lines.append(f"- {count}x `{error}`\n")
    else:
        lines.append("- No errors captured.\n")
    return "".join(lines)


def export_sessions(config: MemoryConfig) -> tuple[list[SessionExport], list[Path]]:
    files = iter_session_files(config.sessions_dir)
    if not files:
        raise SystemExit(f"no Codex session files found in {config.sessions_dir}")
    cleanup_target(config)
    sessions: list[SessionExport] = []
    written: list[Path] = []
    for file_path in files:
        meta, events = parse_session(file_path)
        if not session_is_relevant(meta, config):
            continue
        meaningful = [
            event
            for event in events
            if event.role in {"user", "assistant", "assistant / commentary", "tool_call", "tool_output"}
        ]
        if not meaningful:
            continue
        session = summarize_session(file_path, meta, meaningful, config)
        if config.include_raw:
            session.raw_path.write_text(render_raw(session, config), encoding="utf-8")
        if config.include_summary:
            session.summary_path.write_text(render_summary(session, config), encoding="utf-8")
            written.append(session.summary_path)
        sessions.append(session)
    if config.include_index:
        index_path = config.target_dir / "INDEX.md"
        index_path.write_text(render_index(sessions, config), encoding="utf-8")
        written.append(index_path)
    if config.include_facts:
        facts_path = config.target_dir / "FACTS.md"
        facts_path.write_text(render_facts(sessions, config), encoding="utf-8")
        written.append(facts_path)
    return sessions, written
