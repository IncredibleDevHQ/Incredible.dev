# Resume preamble and change notice

## Resume a failed or interrupted task

A running helper cannot be messaged. A task that failed, stopped early, or was interrupted by a
restart (`check_tasks` and the notice say which) continues in one of two ways:

- **`resume_task(task_id)`** when the notice says its transcript was saved: same id, effort and label,
  picking up where it stopped. The pipeline resumes a run the same way, with the run's id.
- **Otherwise, re-issue the brief** with `start_task` and this on top. The `launch_film` pipeline does
  this itself, once, for a step that fails.

```text
Your previous run on this task stopped before finishing ({{reason}}) at {{the milestone in the progress file}}.
Your work is intact on disk: {{files}}. Resume exactly where you left off: read {{progress file}} first and do not
redo finished milestones or recorded measurements. Everything in the original brief below still applies,
including the deliverables, budget and report. Read `date` now and take your budget from this start. To avoid
another stop, keep tool outputs small (tile and downscale images; don't print large files) and write notes to disk
as you go.

--- original brief ---
{{original brief}}
```

The second failure on the same act: split the act at its next hard cut and give each half to a fresh
builder; the scope is probably too large for one task.

## Change notice (top of the next wave's briefs)

A shared file never changes while builders that read it are working. Between waves, every change goes
out as:

```text
Change notice from the lead (no reply needed). {{file}} changed: {{what changed, in one or two lines}}, because
{{why}}. It affects {{acts or roles}}. Action: {{e.g. "use cardRig instead of card; re-snapshot your comparisons at
the card shots"}}. Nothing else changed.
```

Which moves blur, post effects and glow conventions are cross-act mechanisms: a change to any of them
is announced, every time. An unannounced change gets layered over by one act and logged as a limit by
another, and the final carries the defect.
