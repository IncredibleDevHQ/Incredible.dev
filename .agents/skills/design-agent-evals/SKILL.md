---
name: design-agent-evals
description: Find out whether a change made Design Agent better or worse. Run the eval set or a few tasks before and after against the same model, read the reports, look at the files, and turn a real request that went wrong into a task. Use after changing instructions, skills, checks or models, or when someone asks how good it is.
---

# Evaluate a change

Eval runs spend model and media money. `eval run` prints the budget: show it to the person and get
a yes. The whole set costs about $120 per model; a few tasks cost a few dollars.

1. `uv run design-agent eval list` shows every task with its dollar and minute caps.
2. **Pick the tasks the change touches**, plus one behavior task: still tasks for a stills skill,
   the teaser and film for motion, `exact-copy` for copy rules.
3. **Run before and after, same model, same tasks:**
   `uv run design-agent eval run --task <id> --task <id> --out workspace/out/evals/<label>`.
4. **Read the reports.** Each folder has `report.json`, `README.md` (failed checks per task, spend,
   time) and `files/<task>/`. Open the files and look at them. The graders check outputs, sizes,
   copy and behavior, never taste: a person judges taste.
5. **Report numbers from the reports:** checks passed, spend and time, before against after. Do not
   summarize a run you did not read.
6. **Turn a real failure into a task.** When a thread shows something going wrong, add an entry to
   `tests/eval/tasks.json` modelled on a similar task (the request, expected outputs and sizes, exact
   copy lines, budgets), then `uv run pytest -q tests/unit/test_evals.py`.

Graders and reports: [Evals](../../../docs/evals.md).
