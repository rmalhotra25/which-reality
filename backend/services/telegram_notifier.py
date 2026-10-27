"""
Telegram notifications for Challenge alerts.

Credentials come only from the environment (TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID, set by the user on Render). They are never stored in
the database, never written to the repo, and never logged: log lines in
this module carry only HTTP status codes and exception type names,
because request exception text can embed the request URL, and the URL
contains the bot token.

Every send is best-effort. A notification failure must never break
alert generation, snapshots, or stage graduation, so nothing here
raises.
"""
import logging
import os

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_TIMEOUT_SECONDS = 10
_MAX_LINES = 10
_MAX_BODY_CHARS = 220
_MAX_MESSAGE_CHARS = 4000


def telegram_configured() -> bool:
    """True when both Telegram env vars are set and non-empty."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")) and bool(
        os.environ.get("TELEGRAM_CHAT_ID")
    )


def send_telegram_message(text: str) -> bool:
    """Send one plain-text Telegram message. Returns True only on a
    confirmed 2xx response with ok true. Never raises; when Telegram is
    not configured it returns False without any network call."""
    if not telegram_configured():
        return False
    import requests

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    try:
        resp = requests.post(
            f"{_API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=_TIMEOUT_SECONDS,
        )
        if not (200 <= resp.status_code < 300):
            logger.warning("Telegram send failed: HTTP %s", resp.status_code)
            return False
        if not resp.json().get("ok"):
            logger.warning("Telegram send failed: response ok was not true")
            return False
        return True
    except Exception as e:
        # Log the type only: str(e) can embed the URL, which holds the token.
        logger.warning("Telegram send failed: %s", type(e).__name__)
        return False


def _alert_field(alert, name):
    if isinstance(alert, dict):
        return alert.get(name)
    return getattr(alert, name, None)


def notify_new_alerts(alerts) -> bool:
    """Send ONE batched Telegram message covering newly created alerts.

    Accepts ChallengeAlert rows or plain dicts with title, body, ticker,
    and severity. Returns False for an empty batch.

    The message carries the full instruction, not just a pointer to it:
    each alert's body follows its title line, so the shares, entry, stop,
    and target the Challenge service already computed are in the message
    and the user does not have to open the app to learn what to do.
    Bodies are truncated to _MAX_BODY_CHARS and the whole message is
    capped at _MAX_MESSAGE_CHARS, so one long body can never push the
    batch over Telegram's limit.
    """
    alerts = list(alerts or [])
    if not alerts:
        return False
    lines = [f"TradeIQ Challenge: {len(alerts)} new alert(s)"]
    for alert in alerts[:_MAX_LINES]:
        severity = _alert_field(alert, "severity") or "info"
        ticker = _alert_field(alert, "ticker")
        title = _alert_field(alert, "title") or "Alert"
        if ticker:
            lines.append(f"- [{severity}] {ticker}: {title}")
        else:
            lines.append(f"- [{severity}] {title}")
        body = _alert_field(alert, "body")
        if body:
            flat = " ".join(str(body).split())
            if len(flat) > _MAX_BODY_CHARS:
                flat = flat[:_MAX_BODY_CHARS].rstrip() + "..."
            lines.append(f"  {flat}")
    extra = len(alerts) - _MAX_LINES
    if extra > 0:
        lines.append(f"and {extra} more")
    text = "\n".join(lines)
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[:_MAX_MESSAGE_CHARS].rstrip() + "..."
    return send_telegram_message(text)
