# Codex Loop Controller Notes

## What it does
- Validates a small JSON run packet.
- Supports only `T1_workspace` runs in `/Users/darkfire/.openclaw/workspace`.
- Launches `codex exec` through a real PTY.
- Captures durable artifacts: packet, events, stdout, stderr, result.
- Enforces a wall-clock timeout.

## Current limitations
- One-shot runs only.
- No session reuse.
- No changed-files inventory yet.
- No rollback patch generation yet.
- Stdout/stderr are merged by the PTY path; `stderr.log` is created but empty.
- Acceptance is still external to the controller.

## Next steps
1. Add changed-files capture and pre/post file hashes.
2. Add rollback patch generation for files touched by a run.
3. Emit richer event summaries for the Forge dashboard and activity feed.
4. Add packet schema versioning and stricter validation.
