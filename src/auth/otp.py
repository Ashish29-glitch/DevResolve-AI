"""OTP Generation and Email Sending"""
import random
import string
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from src.config import get_settings

settings = get_settings()


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def get_otp_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes)


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an HTML email when SMTP is enabled; otherwise skip delivery."""
    if not settings.smtp_enabled:
        logging.info(
            "SMTP is disabled. Skipping email to %s. Subject: %s",
            to_email,
            subject,
        )
        return True

    if not settings.smtp_user or not settings.smtp_password:
        raise RuntimeError("SMTP_ENABLED is true but SMTP_USER or SMTP_PASSWORD is missing")

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.from_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception:
        logging.exception("Email send error to %s", to_email)
        raise
    return True


def send_otp_email(to_email: str, otp: str, name: str = "Developer") -> bool:
    """Send an OTP email, or skip it when SMTP is disabled."""
    html = f"""
        <html><body style="font-family: Arial, sans-serif; background: #f4f6fb; padding: 32px;">
        <div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,.08)">
          <div style="text-align:center;margin-bottom:24px">
            <span style="font-size:36px">🔧</span>
            <h2 style="color:#4f46e5;margin:8px 0">DevResolve AI</h2>
          </div>
          <p>Hi <strong>{name}</strong>,</p>
          <p>Your one-time password (OTP) for login is:</p>
          <div style="text-align:center;margin:24px 0">
            <span style="font-size:40px;font-weight:bold;letter-spacing:12px;color:#4f46e5">{otp}</span>
          </div>
          <p style="color:#6b7280;font-size:14px">This OTP expires in <strong>{settings.otp_expire_minutes} minutes</strong>. Do not share it with anyone.</p>
          <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0"/>
          <p style="color:#9ca3af;font-size:12px;text-align:center">DevResolve AI — Smart Issue Tracking System</p>
        </div>
        </body></html>
        """
    return send_email(to_email, "DevResolve AI - Your OTP Code", html)


def send_welcome_email(to_email: str, name: str, project: str, manager: str) -> bool:
    """Send an access-approved email, or skip it when SMTP is disabled."""
    html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#f4f6fb;padding:32px;">
        <div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;padding:32px;">
          <h2 style="color:#4f46e5">Welcome to DevResolve AI! 🚀</h2>
          <p>Hi <strong>{name}</strong>,</p>
          <p>Your access to project <strong>{project}</strong> has been approved by <strong>{manager}</strong>.</p>
          <p>You can now log in and start raising tickets, adding daily updates, and collaborating with your team.</p>
          <a href="{settings.app_url}/auth/login" style="display:inline-block;margin:16px 0;padding:12px 24px;background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none">Login Now</a>
        </div>
        </body></html>
        """
    return send_email(to_email, "DevResolve AI - Access Approved!", html)
