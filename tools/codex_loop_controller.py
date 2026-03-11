#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import select
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

WORKSPACE_ROOT = "/Users/darkfire/.openclaw/workspace"
SUPPORTED_TIER = "T1_workspace"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_workspace_path(path: Path) -> str:
    return str(path.resolve().relative_to(Path(WORKSPACE_ROOT).resolve()))


def workspace_files() -> dict[str, str]:
    root = Path(WORKSPACE_ROOT)
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        try:
            files[rel_workspace_path(path)] = sha256_file(path)
        except (OSError, ValueError):
            continue
    return files


def compute_file_changes(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    common = before_keys & after_keys
    modified = sorted([p for p in common if before[p] != after[p]])
    touched = sorted(set(added) | set(removed) | set(modified))
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "touched": touched,
    }


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_packet(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    required = [
        "run_id",
        "workspace_root",
        "task",
        "approval_tier",
        "artifacts",
        "timeouts",
    ]
    for key in required:
        if key not in data:
            raise ValueError(f"missing required field: {key}")
    if data["workspace_root"] != WORKSPACE_ROOT:
        raise ValueError("workspace_root must be /Users/darkfire/.openclaw/workspace")
    if data["approval_tier"] != SUPPORTED_TIER:
        raise ValueError(f"only {SUPPORTED_TIER} is supported")
    artifacts = data["artifacts"]
    if not isinstance(artifacts, dict) or "dir" not in artifacts:
        raise ValueError("artifacts.dir is required")
    timeouts = data["timeouts"]
    if not isinstance(timeouts, dict) or "wall_sec" not in timeouts:
        raise ValueError("timeouts.wall_sec is required")
    if not isinstance(timeouts["wall_sec"], int) or timeouts["wall_sec"] <= 0:
        raise ValueError("timeouts.wall_sec must be a positive integer")
    return data


def append_event(events_path: Path, kind: str, **fields: Any) -> None:
    event = {"ts": now_iso(), "kind": kind, **fields}
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def build_rollback_patch(artifact_dir: Path, touched: list[str]) -> int:
    patch_path = artifact_dir / "rollback.patch"
    if not touched:
        patch_path.write_text("", encoding="utf-8")
        return 0
    cmd = ["git", "-C", WORKSPACE_ROOT, "diff", "--"] + touched
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    patch_path.write_text(proc.stdout, encoding="utf-8")
    return len(proc.stdout.encode("utf-8"))


def run_packet(packet: Dict[str, Any]) -> int:
    run_id = packet["run_id"]
    artifact_dir = Path(packet["artifacts"]["dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    packet_path = artifact_dir / "packet.json"
    events_path = artifact_dir / "events.jsonl"
    stdout_path = artifact_dir / "stdout.log"
    stderr_path = artifact_dir / "stderr.log"
    result_path = artifact_dir / "result.json"
    changed_files_path = artifact_dir / "changed_files.json"
    file_hashes_path = artifact_dir / "file_hashes.json"

    write_json(packet_path, packet)
    stderr_path.write_text("", encoding="utf-8")
    append_event(events_path, "run.queued", run_id=run_id)

    before = workspace_files()
    append_event(events_path, "workspace.snapshot", run_id=run_id, phase="before", file_count=len(before))

    cmd = [
        "codex",
        "exec",
        "--model",
        "gpt-5.4",
        "--sandbox",
        "workspace-write",
        "-C",
        WORKSPACE_ROOT,
        packet["task"],
    ]

    master_fd, slave_fd = pty.openpty()
    start = time.time()
    append_event(events_path, "pty.open", run_id=run_id)
    append_event(events_path, "run.start", run_id=run_id, argv=cmd)

    proc = subprocess.Popen(
        cmd,
        cwd=WORKSPACE_ROOT,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    timed_out = False
    stdout_chunks: list[bytes] = []

    try:
        while True:
            if proc.poll() is not None:
                break
            if time.time() - start > packet["timeouts"]["wall_sec"]:
                timed_out = True
                append_event(events_path, "run.timeout", run_id=run_id)
                os.killpg(proc.pid, signal.SIGTERM)
                time.sleep(1)
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                break
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if chunk:
                    stdout_chunks.append(chunk)
                else:
                    break
        while True:
            try:
                chunk = os.read(master_fd, 4096)
                if not chunk:
                    break
                stdout_chunks.append(chunk)
            except OSError:
                break
    finally:
        os.close(master_fd)

    stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stdout_path.write_text(stdout_text, encoding="utf-8")

    returncode = proc.wait() if proc.poll() is None else proc.returncode

    after = workspace_files()
    append_event(events_path, "workspace.snapshot", run_id=run_id, phase="after", file_count=len(after))
    changes = compute_file_changes(before, after)
    write_json(changed_files_path, changes)
    append_event(events_path, "artifact.write", run_id=run_id, path=str(changed_files_path), touched_count=len(changes["touched"]))

    touched_hashes = {
        "before": {path: before.get(path) for path in changes["touched"]},
        "after": {path: after.get(path) for path in changes["touched"]},
    }
    write_json(file_hashes_path, touched_hashes)
    append_event(events_path, "artifact.write", run_id=run_id, path=str(file_hashes_path))

    rollback_bytes = build_rollback_patch(artifact_dir, changes["touched"])
    append_event(events_path, "artifact.write", run_id=run_id, path=str(artifact_dir / "rollback.patch"), bytes=rollback_bytes)

    result = {
        "run_id": run_id,
        "ok": (returncode == 0 and not timed_out),
        "returncode": returncode,
        "timed_out": timed_out,
        "started_at": datetime.fromtimestamp(start, timezone.utc).isoformat().replace("+00:00", "Z"),
        "ended_at": now_iso(),
        "artifact_dir": str(artifact_dir),
        "changed_files": changes,
    }
    write_json(result_path, result)
    append_event(events_path, "run.end", run_id=run_id, returncode=returncode, timed_out=timed_out, ok=result["ok"])
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal PTY-backed Codex loop from a JSON packet.")
    parser.add_argument("--packet", required=True, help="Path to the run packet JSON file")
    args = parser.parse_args()
    try:
        packet = load_packet(Path(args.packet))
        return run_packet(packet)
    except Exception as e:
        print(f"controller failure: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
