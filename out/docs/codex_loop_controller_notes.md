# Codex Loop Controller Notes

## What it does
- Validates a small JSON run packet.
- Supports only `T1_workspace` runs in `/Users/darkfire/.openclaw/workspace`.
- Launches `codex exec` through a real PTY.
- Captures durable artifacts: packet, events, stdout, stderr, result.
- Captures `changed_files.json` and touched file hashes.
- Generates a `rollback.patch` from touched files.
- Enforces a wall-clock timeout.

## Current limitations
- One-shot runs only.
- No session reuse.
- Stdout/stderr are merged by the PTY path; `stderr.log` is created but empty.
- Rollback patch generation uses `git diff`, so it is strongest when the workspace is treated as a real repo baseline.
- Acceptance is still external to the controller.

## Next steps
1. Add packet schema versioning and stricter validation.
2. Emit richer event summaries for the Forge dashboard and activity feed.
3. Add acceptance-test execution and architect decision artifacts.
4. Separate durable run storage from the working repo if artifact volume grows.
