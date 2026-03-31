"""Email sending via Resend for OpenRAROC transactional emails."""

import os
import logging

import resend

log = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "OpenRAROC <noreply@openraroc.com>")
APP_URL = os.environ.get("WEBAPP_URL", "https://openraroc.com")

# ── Shared styles ────────────────────────────────────────────────

_STYLE = """
<style>
  body { margin: 0; padding: 0; background: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .container { max-width: 560px; margin: 0 auto; padding: 32px 24px; }
  .header { text-align: center; padding: 24px 0 16px; border-bottom: 1px solid #334155; margin-bottom: 24px; }
  .header h1 { color: #f1f5f9; font-size: 22px; margin: 0; }
  .header .sub { color: #94a3b8; font-size: 13px; margin-top: 4px; }
  .content { color: #cbd5e1; font-size: 15px; line-height: 1.6; }
  .content h2 { color: #f1f5f9; font-size: 18px; margin: 0 0 12px; }
  .content p { margin: 0 0 16px; }
  .content a { color: #3b82f6; }
  .key-box { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 18px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 14px; color: #3b82f6; margin: 16px 0; word-break: break-all; }
  .btn { display: inline-block; background: #3b82f6; color: #ffffff !important; text-decoration: none; padding: 12px 28px; border-radius: 8px; font-weight: 600; font-size: 15px; margin: 16px 0; }
  .steps { background: #1e293b; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }
  .steps li { color: #cbd5e1; margin-bottom: 8px; }
  .footer { text-align: center; padding-top: 24px; border-top: 1px solid #334155; margin-top: 24px; color: #64748b; font-size: 12px; }
  .alert { background: #7f1d1d; border: 1px solid #991b1b; border-radius: 8px; padding: 14px 18px; color: #fca5a5; margin: 16px 0; }
</style>
"""


def _wrap(body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_STYLE}</head>
<body><div class="container">
  <div class="header"><h1>OpenRAROC</h1><div class="sub">See yourself through your banker's eyes</div></div>
  <div class="content">{body}</div>
  <div class="footer">OpenRAROC &middot; <a href="{APP_URL}" style="color:#64748b;">openraroc.com</a></div>
</div></body></html>"""


def _send(to: str, subject: str, html: str) -> bool:
    if not resend.api_key:
        log.warning("RESEND_API_KEY not set, skipping email to %s: %s", to, subject)
        return False
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        log.error("Failed to send email to %s: %s", to, e)
        return False


# ── Email types ──────────────────────────────────────────────────

def send_welcome(email: str, api_key: str) -> bool:
    body = f"""
    <h2>Welcome to OpenRAROC Pro</h2>
    <p>Your subscription is active. You now have access to all 35 bank profiles
    across 13 countries.</p>

    <p><strong>Your API key:</strong></p>
    <div class="key-box">{api_key}</div>

    <p><strong>Get started:</strong></p>
    <ol class="steps">
      <li>Upload your portfolio at <a href="{APP_URL}">{APP_URL}</a></li>
      <li>Compare how 35 banks evaluate your credit facilities</li>
      <li>Use the solver to find minimum spreads per bank</li>
      <li>Use the API key above for CLI and MCP agent access</li>
    </ol>

    <a href="{APP_URL}" class="btn">Open OpenRAROC</a>

    <p style="color:#94a3b8;font-size:13px;">Keep your API key safe. You can
    find it anytime at <a href="{APP_URL}">{APP_URL}</a> in the Pro section.</p>
    """
    return _send(email, "Welcome to OpenRAROC Pro", _wrap(body))


def send_renewal_reminder(email: str, days_left: int) -> bool:
    if days_left <= 7:
        urgency = "in 7 days"
        subject = "Your OpenRAROC Pro subscription renews in 7 days"
    else:
        urgency = "in 30 days"
        subject = "Your OpenRAROC Pro subscription renews in 30 days"

    body = f"""
    <h2>Subscription renewal {urgency}</h2>
    <p>Your OpenRAROC Pro subscription will automatically renew {urgency}.
    No action is needed if you'd like to continue.</p>

    <p>If you need to update your payment method or manage your subscription,
    click below:</p>

    <a href="{APP_URL}" class="btn">Manage Subscription</a>

    <p style="color:#94a3b8;font-size:13px;">Your Pro access includes all 35 bank
    profiles, API access, and data updates throughout the year.</p>
    """
    return _send(email, subject, _wrap(body))


def send_data_update(email: str, message: str) -> bool:
    body = f"""
    <h2>Bank Data Updated</h2>
    <p>{message}</p>

    <p>Your RAROC calculations now reflect the latest regulatory filings.
    Log in to see the updated results for your portfolio.</p>

    <a href="{APP_URL}" class="btn">View Updated Data</a>

    <p style="color:#94a3b8;font-size:13px;">Data updates are included with your
    OpenRAROC Pro subscription. Bank profiles are refreshed annually from
    Pillar 3 regulatory disclosures.</p>
    """
    return _send(email, "OpenRAROC: Bank data updated", _wrap(body))


def send_payment_failed(email: str) -> bool:
    body = f"""
    <h2>Payment Failed</h2>
    <div class="alert">
      We were unable to process your OpenRAROC Pro subscription payment.
      Your access may be interrupted if the payment is not resolved.
    </div>

    <p>Please update your payment method to continue using OpenRAROC Pro
    with all 35 bank profiles.</p>

    <a href="{APP_URL}" class="btn">Update Payment Method</a>

    <p style="color:#94a3b8;font-size:13px;">If you believe this is an error,
    please contact us and we'll help resolve it.</p>
    """
    return _send(email, "Action required: OpenRAROC payment failed", _wrap(body))
