"""Email tool — composes and sends emails via SMTP."""

from __future__ import annotations

import os
import smtplib
import time
from email.message import EmailMessage
from typing import Any

from loguru import logger

from src.core.models import RiskLevel, ToolResult
from src.tools.base import BaseTool


class EmailTool(BaseTool):
    """Compose and send emails via SMTP. Requires user confirmation."""

    name = "email_tool"
    description = "Compose and send emails. Always requires user confirmation."
    risk_level = RiskLevel.DANGEROUS
    parameters_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body (plain text)"},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["to", "subject", "body"],
    }

    async def validate_args(self, **kwargs: Any) -> tuple[bool, str]:
        for field in ("to", "subject", "body"):
            if not kwargs.get(field, "").strip():
                return False, f"'{field}' is required"
        to = kwargs["to"]
        if "@" not in to:
            return False, f"Invalid email address: {to}"
        return True, ""

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = time.monotonic()
        to = kwargs.get("to", "").strip()
        subject = kwargs.get("subject", "").strip()
        body = kwargs.get("body", "").strip()
        dry_run = kwargs.get("dry_run", False)
        
        if dry_run:
            preview = f"[dry-run] Would send email:\n  To: {to}\n  Subject: {subject}\n  Body: {body[:100]}..."
            return self._timed_result(start, True, output=preview)
        
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        
        if not smtp_host:
            return self._timed_result(
                start, False,
                error="SMTP not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS in .env"
            )
        
        try:
            msg = EmailMessage()
            msg["To"] = to
            msg["From"] = smtp_user
            msg["Subject"] = subject
            msg.set_content(body)
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            
            logger.warning(f"Email sent to {to}: {subject}")
            return self._timed_result(
                start, True,
                output=f"Email sent to {to}",
                side_effects=[f"email_sent:{to}"],
            )
        except smtplib.SMTPException as e:
            return self._timed_result(start, False, error=f"SMTP error: {e}")
        except OSError as e:
            return self._timed_result(start, False, error=f"Network error: {e}")
