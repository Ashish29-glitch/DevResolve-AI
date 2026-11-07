"""OTP Generation and Email Sending"""
import random
import string
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.config import get_settings

settings = get_settings()


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def get_otp_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes)


def send_otp_email(to_email: str, otp: str, name: str = "Developer") -> bool:
    """Send OTP via Gmail SMTP. Returns True on success."""
    if not settings.smtp_user or not settings.smtp_password:
        # Dev mode: print OTP
        print(f"[DEV MODE] OTP for {to_email}: {otp}")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "DevResolve AI - Your OTP Code"
        msg["From"] = settings.from_email
        msg["To"] = to_email

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
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.from_email, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email send error: {e}")
        return False


def send_welcome_email(to_email: str, name: str, project: str, manager: str) -> bool:
    """Send welcome email to approved developer."""
    if not settings.smtp_user:
        print(f"[DEV MODE] Welcome email to {to_email}")
        return True
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🎉 DevResolve AI - Access Approved!"
        msg["From"] = settings.from_email
        msg["To"] = to_email
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
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.from_email, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Welcome email error: {e}")
        return False
