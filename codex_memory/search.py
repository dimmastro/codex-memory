from __future__ import annotations

from pathlib import Path

from .config import MemoryConfig


def base_dirs(config: MemoryConfig, machine: str | None, all_machines: bool) -> list[Path]:
    if all_machines:
        if not config.project_memory_root.exists():
            return []
        return sorted(path for path in config.project_memory_root.iterdir() if path.is_dir())
    name = machine or config.machine_name
    return [config.render_memory_path(name)]


def iter_files(config: MemoryConfig, base_dir: Path, mode: str) -> list[Path]:
    files: list[Path] = []
    if mode in {"summary", "all"}:
        files.extend(sorted((base_dir / config.summary_dir_name).glob("*.md")))
        for name in ("INDEX.md", "FACTS.md"):
            path = base_dir / name
            if path.exists():
                files.append(path)
    if mode in {"raw", "all"}:
        files.extend(sorted((base_dir / config.raw_dir_name).glob("*.md")))
    return files


def search_file(path: Path, needle: str, case_sensitive: bool) -> list[str]:
    results: list[str] = []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    needle_cmp = needle if case_sensitive else needle.lower()
    for idx, line in enumerate(lines, start=1):
        hay = line if case_sensitive else line.lower()
        if needle_cmp in hay:
            results.append(f"{path}:{idx}: {line.strip()}")
    return results


def run_search(config: MemoryConfig, query: str, mode: str, case_sensitive: bool, machine: str | None, all_machines: bool) -> int:
    dirs = base_dirs(config, machine, all_machines)
    files: list[Path] = []
    for base_dir in dirs:
        files.extend(iter_files(config, base_dir, mode))
    if not files:
        searched = config.project_memory_root if all_machines else dirs[0]
        raise SystemExit(f"no exported files found in {searched}")
    matches = 0
    for path in files:
        for line in search_file(path, query, case_sensitive):
            print(line)
            matches += 1
    return matches
