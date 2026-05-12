from __future__ import annotations

import argparse
import json

from .config import add_common_arguments, dump_config, ensure_python_version, load_config
from .exporter import export_sessions
from .search import run_search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Config-driven Codex CLI memory tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export Codex sessions into project memory")
    add_common_arguments(export_parser)

    search_parser = subparsers.add_parser("search", help="search exported project memory")
    add_common_arguments(search_parser)
    search_parser.add_argument("query", help="substring to search")
    search_parser.add_argument("--mode", choices=("summary", "raw", "all"), default="summary")
    search_parser.add_argument("--case-sensitive", action="store_true")
    search_parser.add_argument("--machine", help="search only one machine directory")
    search_parser.add_argument("--all-machines", action="store_true")

    show_parser = subparsers.add_parser("config", help="show effective configuration")
    add_common_arguments(show_parser)
    show_parser.add_argument("action", choices=("show",), nargs="?", default="show")
    show_parser.add_argument("--json", action="store_true", help="print config as json")

    doctor_parser = subparsers.add_parser("doctor", help="show path diagnostics")
    add_common_arguments(doctor_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_python_version()
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args)

    if args.command == "export":
        sessions, written = export_sessions(config)
        for path in written:
            print(path)
        print(f"exported {len(sessions)} session file(s) to {config.target_dir}")
        return 0

    if args.command == "search":
        matches = run_search(
            config=config,
            query=args.query,
            mode=args.mode,
            case_sensitive=args.case_sensitive,
            machine=args.machine,
            all_machines=args.all_machines,
        )
        return 0 if matches else 1

    if args.command == "config":
        if args.json:
            print(json.dumps(config.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(dump_config(config))
        return 0

    if args.command == "doctor":
        print(f"project_root = {config.project_root}")
        print(f"sessions_dir = {config.sessions_dir}")
        print(f"storage_root = {config.storage_root}")
        print(f"target_dir = {config.target_dir}")
        print(f"project_config_path = {config.project_config_path}")
        print(f"local_config_path = {config.local_config_path}")
        print(f"machine_name = {config.machine_name}")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2
