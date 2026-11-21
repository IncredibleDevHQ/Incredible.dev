from unittest.mock import patch

from design_agent.config import Settings
from design_agent.surfaces.web.invite_mail import send_invitation

INVITE = (
    "guest@example.com",
    "Studio <Design>",
    "owner@example.com",
    "https://studio.example/invite/abc",
)


def test_smtp_delivery_requires_tls_before_sending_credentials():
    settings = Settings(
        _env_file=None,
        smtp_host="smtp.example.com",
        smtp_from="studio@example.com",
        smtp_username="studio",
        smtp_password="synthetic-test",
    )
    with patch("design_agent.surfaces.web.invite_mail.smtplib.SMTP") as smtp:
        relay = smtp.return_value.__enter__.return_value
        assert send_invitation(settings, *INVITE)
        assert [call[0] for call in relay.method_calls] == ["starttls", "login", "send_message"]
        message = relay.send_message.call_args.args[0]
        assert INVITE[3] in message.get_body(preferencelist=("plain",)).get_content()
        assert "Studio &lt;Design&gt;" in message.get_body().get_content()
        relay.reset_mock()
        assert not send_invitation(settings.model_copy(update={"smtp_starttls": False}), *INVITE)
        relay.login.assert_not_called()
        relay.send_message.assert_not_called()


def test_unconfigured_or_unreachable_relay_reports_delivery_failure():
    settings = Settings(_env_file=None)
    with patch("design_agent.surfaces.web.invite_mail.smtplib.SMTP", side_effect=OSError) as smtp:
        assert not send_invitation(settings, *INVITE)
        smtp.assert_not_called()
        assert not send_invitation(
            settings.model_copy(
                update={
                    "smtp_host": "smtp.example.com",
                    "smtp_from": "studio@example.com",
                }
            ),
            *INVITE,
        )
        smtp.assert_called_once()
