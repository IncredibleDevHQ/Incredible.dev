"""The design eval set and behavior evals (SPEC §20.4-20.5): tasks, graders, runner, report.

Graders are deterministic: they read the run's trace (every message and tool call) and measure the
delivered files with the same gates the agent uses. There is no model judging taste; taste is the
human review checklist each report carries.
"""
