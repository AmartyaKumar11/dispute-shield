from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from backend.config import settings

log = structlog.get_logger(__name__)


class EmailProvider:
    """Sends real emails via Gmail SMTP."""

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> bool:
        if not settings.smtp_user or not settings.smtp_password:
            log.warning("smtp.not_configured", to=to_email, subject=subject)
            return False

        try:
            from_email = settings.smtp_from_email or settings.smtp_user
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{settings.smtp_from_name} <{from_email}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            await asyncio.to_thread(self._send_smtp, msg)
            log.info("smtp.sent", to=to_email, subject=subject)
            return True
        except Exception:
            log.exception("smtp.send_failed", to=to_email, subject=subject)
            return False

    def _send_smtp(self, msg: MIMEMultipart) -> None:
        password = settings.smtp_password.replace(" ", "")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, password)
            server.send_message(msg)

    async def send_intervention_email(
        self,
        to_email: str,
        customer_name: str,
        order_id: str,
        intervention_message: str,
        product_name: str,
        amount: float,
    ) -> bool:
        subject = f"Update on your order {order_id} — DisputeShield"
        safe_msg = intervention_message.replace("\n", "<br/>")
        body_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #1a1a2e; margin: 0 0 10px 0;">Order Update</h2>
                <p style="color: #666; margin: 0; font-size: 14px;">
                    Hi {customer_name} — Order #{order_id} · ₹{amount:,.2f} · {product_name}
                </p>
            </div>
            <div style="padding: 0 10px; line-height: 1.6; color: #333;">{safe_msg}</div>
            <div style="margin-top: 30px; padding: 15px; background: #e8f5e9; border-radius: 8px; text-align: center;">
                <p style="margin: 0; color: #2e7d32; font-size: 14px;">
                    Simply reply to this email and we'll respond within 24 hours.
                </p>
            </div>
            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #999; font-size: 12px; text-align: center;">
                Sent by DisputeShield on behalf of the merchant
            </div>
        </div>
        """
        body_text = f"""Order Update — {order_id}

Hi {customer_name},

{intervention_message}

Reply to this email and we'll respond within 24 hours.

— DisputeShield
"""
        return await self.send_email(to_email, subject, body_html, body_text)


email_provider = EmailProvider()
