# Build Log

## 2026-03-11 — Project 1: Codex Loop Controller v2

### Decision
Start with the autonomy-critical substrate, not secondary conveniences.

Why this first:
- The Forge needs a governable worker before it needs more tools.
- Codex already proved it can reason well while still failing delivery contracts.
- Therefore the next leverage point is stronger supervision: artifact capture, changed-files visibility, and rollback primitives.

### What I am building
- Upgrade `tools/codex_loop_controller.py` from v1 to v2.
- Add changed-files capture.
- Add pre/post file hashes for tracked touched files.
- Add rollback patch generation.
- Keep the implementation small, deterministic, and local-first.

### Why this shape
I chose to extend the existing controller instead of splitting into more files because:
- v1 is still small enough to reason about in one place
- the next missing capabilities are tightly coupled to the run lifecycle
- adding more abstractions now would increase surface area faster than utility

### Project completion criterion
This project is complete when:
- the controller writes `changed_files.json`
- the controller writes `file_hashes.json`
- the controller writes `rollback.patch`
- a live run succeeds and produces those artifacts
- the project is committed and pushed
