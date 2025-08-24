"""Create and monitor local canary files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    info = path.stat()
    return {
        "exists": True,
        "sha256": hash_file(path),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "file_id": f"{info.st_dev}:{info.st_ino}",
    }


def compare(expected: dict[str, object], actual: dict[str, object]) -> list[str]:
    if expected.get("exists") and not actual.get("exists"):
        return ["deleted"]
    if not expected.get("exists") and actual.get("exists"):
        return ["created"]
    if not actual.get("exists"):
        return []
    events = []
    if expected.get("file_id") != actual.get("file_id"):
        events.append("replaced")
    if expected.get("sha256") != actual.get("sha256"):
        events.append("content_changed")
    elif expected.get("mtime_ns") != actual.get("mtime_ns"):
        events.append("metadata_changed")
    return events


def default_state(path: Path) -> Path:
    return path.with_name(path.name + ".dw-honey.json")


def write_state(path: Path, target: Path) -> None:
    data = {
        "schema": "dispersal-wolves/honeyfile/v1",
        "target": target.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected": snapshot(target),
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_state(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def send_webhook(url: str, event: dict[str, object], allow_http: bool) -> None:
    if not url.startswith("https://") and not (allow_http and url.startswith("http://")):
        raise ValueError("webhooks require HTTPS; use --allow-http only on trusted local networks")
    request = urllib.request.Request(
        url,
        data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "dispersal-honeyfile/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status >= 400:
            raise RuntimeError(f"webhook returned HTTP {response.status}")


def command_create(args: argparse.Namespace) -> int:
    if args.target.exists() and not args.force:
        print(f"Refusing to overwrite existing file: {args.target}", file=sys.stderr)
        return 2
    args.target.parent.mkdir(parents=True, exist_ok=True)
    marker = secrets.token_hex(16)
    content = args.content if args.content is not None else f"Dispersal Wolves canary {marker}\n"
    args.target.write_text(content, encoding="utf-8", newline="\n")
    state_path = args.state or default_state(args.target)
    write_state(state_path, args.target)
    print(f"Created canary: {args.target}\nState: {state_path}")
    return 0


def inspect(target: Path, state_path: Path) -> tuple[list[str], dict[str, object]]:
    state = read_state(state_path)
    actual = snapshot(target)
    return compare(state["expected"], actual), actual


def command_status(args: argparse.Namespace) -> int:
    state_path = args.state or default_state(args.target)
    try:
        events, actual = inspect(args.target, state_path)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"Cannot read canary state: {exc}", file=sys.stderr)
        return 2
    report = {"target": str(args.target), "status": "changed" if events else "intact", "events": events, "actual": actual}
    print(json.dumps(report, indent=2) if args.format == "json" else f"{report['status'].upper()}: {args.target}" + (f" ({', '.join(events)})" if events else ""))
    return 1 if events else 0


def command_watch(args: argparse.Namespace) -> int:
    state_path = args.state or default_state(args.target)
    last_events: tuple[str, ...] = ()
    print(f"Watching {args.target}; press Ctrl+C to stop.")
    try:
        while True:
            events, actual = inspect(args.target, state_path)
            signature = tuple(events)
            if events and signature != last_events:
                event = {
                    "schema": "dispersal-wolves/honeyfile-event/v1",
                    "time": datetime.now(timezone.utc).isoformat(),
                    "target": args.target.name,
                    "events": events,
                    "actual": actual,
                }
                print(json.dumps(event), flush=True)
                if args.webhook:
                    try:
                        send_webhook(args.webhook, event, args.allow_http)
                    except Exception as exc:  # delivery failure must not stop monitoring
                        print(f"Webhook delivery failed: {exc}", file=sys.stderr)
            last_events = signature
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("target", type=Path)
    create.add_argument("--state", type=Path)
    create.add_argument("--content")
    create.add_argument("--force", action="store_true")
    create.set_defaults(func=command_create)
    status = sub.add_parser("status")
    status.add_argument("target", type=Path)
    status.add_argument("--state", type=Path)
    status.add_argument("--format", choices=("text", "json"), default="text")
    status.set_defaults(func=command_status)
    watch = sub.add_parser("watch")
    watch.add_argument("target", type=Path)
    watch.add_argument("--state", type=Path)
    watch.add_argument("--interval", type=float, default=2.0)
    watch.add_argument("--webhook")
    watch.add_argument("--allow-http", action="store_true")
    watch.set_defaults(func=command_watch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
