"""MDA native Slack channel: mentions, DMs, thread replies, file transfer and approval cards."""

from pathlib import Path

from managed_deepagents import channels

from design_agent.config import Settings

ICON = "slack-icon.png"
_settings = Settings()

channel = channels.slack(
    name=_settings.slack_name,
    description=_settings.slack_description,
    icon=ICON if Path(__file__).with_name(ICON).is_file() else None,
    background_color=_settings.slack_background_color,
    trigger_on_all_messages=_settings.slack_trigger_on_all_messages,
    allow_bot_triggers=_settings.slack_allow_bot_triggers,
)
