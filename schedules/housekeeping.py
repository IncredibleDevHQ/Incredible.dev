"""Every 15 minutes: housekeeping (`src/design_agent/middleware/housekeeping.py`).

It sweeps background work a restart killed and tidies this agent's expired one-time schedules,
then ends in code before any model call. It posts nothing.
"""

from managed_deepagents import define_schedule

schedule = define_schedule(cron="*/15 * * * *", prompt="<housekeeping>")
