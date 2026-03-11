# Codex Autonomy Loop v1

## Goal
Run a local architect->worker loop where Zarathustra in OpenClaw plans work, approves a bounded run packet, launches `codex` in `/Users/darkfire/.openclaw/workspace`, and then evaluates the result from artifacts, traces, and acceptance checks rather than from self-report.

v1 should optimize for three things first: reliable PTY-backed execution, gate-first safety, and operator-visible traces. It should not depend on the older non-TTY connector path that currently fails with `stdin is not a terminal`.

## Roles and authority boundaries
- **Zarathustra / OpenClaw architect** owns task framing, approval tier, acceptance tests, cancellation, and final judgment.
- **Codex worker runtime (`codex`)** executes only inside the approved packet. It can propose expansions, but it cannot widen its own permissions.
- **Loop controller** is deterministic glue: validate packet, allocate PTY, launch/stop `codex`, collect artifacts, and enforce policy/timeouts.
- **Human** is only needed for escalations above the architect’s current standing authority.
- **Hard rule:** if the packet, trace sink, or rollback path is missing, the run downgrades to proposal-only.

## Control loop state machine
1. **Drafted**: Zarathustra creates a run packet with task, scope, tier, tests, and rollback plan.
2. **Validated**: controller schema-validates the packet and resolves allowlists, paths, and time budgets.
3. **Approved**: architect explicitly approves the packet for launch.
4. **Launching**: controller opens a real PTY, starts `codex`, and emits `run.start` plus transport events.
5. **Running**: `codex` works within packet limits while the controller streams JSONL events, stdout/stderr summaries, changed files, and checkpoints.
6. **Blocked**: run pauses if `codex` requests an action outside its tier, loses observability, or hits a policy gate.
7. **Completed**: `codex` exits or is stopped; controller writes final artifacts, exit status, and touched-file inventory.
8. **Evaluating**: Zarathustra scores the run against acceptance tests and Forge rubrics, then emits `accept`, `revise`, `rollback`, or `reject`.
9. **Closed**: controller either marks the run accepted, launches a follow-up packet, or performs bounded rollback on files proven to belong to this run.

## Run packet schema
Required fields:
- `run_id`, `created_at`, `architect`, `worker`
- `workspace_root`
- `task`
- `context_refs`
- `approval_tier`
- `capabilities`
- `acceptance_tests`
- `rollback_plan`
- `timeouts`
- `artifacts`
- `eval`

Compact example:
```json
{"run_id":"crun_2026-03-11_001","architect":"zarathustra_openclaw","worker":"codex","workspace_root":"/Users/darkfire/.openclaw/workspace","task":"Repair PTY-backed Codex launch path and expose transport status","context_refs":["memory/2026-03-10.md","SECURITY_CONTRACT.md"],"approval_tier":"T1_workspace","capabilities":{"write_paths":["/Users/darkfire/.openclaw/workspace"],"allow_exec":true,"allow_network":false,"allow_external_side_effects":false},"acceptance_tests":["no 'stdin is not a terminal' failure","run emits run.start and run.end","changed_files.json is present"],"rollback_plan":{"mode":"reverse_patch_if_clean","scope":"files_touched_by_run"},"timeouts":{"launch_sec":20,"idle_sec":120,"wall_sec":1800},"artifacts":{"dir":"memory/codex_loop/runs/crun_2026-03-11_001"},"eval":{"rubric":"forge-core-rubric","scorecard":"evals/forge_builder_scorecard.json"}}
```

## Approval policy tiers
- **T0 Proposal**: read-only reasoning, plans, and diffs; no file writes, no external effects.
- **T1 Workspace**: write and run local checks only inside `/Users/darkfire/.openclaw/workspace`; no network, no messaging, no system changes. This should be the default v1 tier.
- **T2 Guarded Local**: workspace writes plus explicit allowlisted local commands or allowlisted fetches declared in the packet; architect approval required up front.
- **T3 External / Irreversible**: messaging, posting, installs, gateway/config changes, secrets, identity, money, or anything outside the workspace. Off by default; each action needs explicit approval and separate audit entries.

## Observability and logging
Each run should produce a durable artifact folder such as `memory/codex_loop/runs/<run_id>/` with:
- `packet.json`
- `events.jsonl`
- `stdout.log`
- `stderr.log`
- `result.json`
- `changed_files.json`
- `rollback.patch`
- `architect_decision.json`

Event logging should be append-only JSONL, metadata-first, and safe to mirror into the existing activity-feed surfaces. Minimum event kinds:
- `run.queued`
- `run.start`
- `pty.open`
- `worker.output`
- `artifact.write`
- `approval.request`
- `policy.block`
- `run.end`
- `rollback.start`
- `rollback.end`

The loop should reuse current Forge observability habits:
- mirror operator-safe summaries into the activity feed
- keep payloads hashed or summarized unless explicit debug is enabled
- make runs indexable and replayable with the existing artifact, reliability, and replay tools

## Failure modes and rollback
Primary failure modes:
- PTY allocation or transport failure
- `codex` hang or partial output stream
- schema-invalid packet or missing acceptance test
- trace sink unavailable
- worker edits outside packet scope
- dirty-worktree conflicts that make naive revert unsafe
- false acceptance because the architect relied on narrative instead of artifacts

Rollback policy:
- capture pre-run hashes for any file the run touches
- generate a reverse patch only for those files
- auto-rollback only if preimage hashes still match and no unrelated user edits intervened
- otherwise stop, preserve artifacts, and surface a conflict report for architect review

If observability breaks mid-run, the run should fail closed and be judged non-accepting until replayable artifacts exist.

## Minimal first implementation in this workspace
- Add a PTY-backed loop controller that launches `codex` directly and never falls back to the broken non-TTY connector path.
- Keep v1 to one-shot runs, not persistent sessions. Session reuse should wait until PTY behavior is stable.
- Store runs under a single new root such as `memory/codex_loop/runs/` using JSON/JSONL-first artifacts.
- Feed safe event summaries into the existing activity-feed pipeline and current Forge dashboard at `http://localhost:8088/`.
- Reuse existing Forge evaluation assets for architect scoring and existing artifact/reliability/replay utilities for reporting.
- Start with `T1_workspace` only: local workspace edits, local tests, no outbound network or messaging.

## Next 3 experiments
1. **PTY transport bakeoff**: compare direct Python PTY, `script`, and `tmux` wrappers for `codex`; measure launch success, stream fidelity, interrupt handling, and elimination of the terminal error.
2. **One-shot vs reused worker session**: once PTY is stable, compare clean-per-run workers against reused sessions on latency, contamination, rework rate, and acceptance rate.
3. **Architect gate calibration**: run the same task set across `T0`/`T1`/`T2` policies and score false accepts, false refuses, rollback rate, and human intervention frequency using the existing Forge rubrics.
