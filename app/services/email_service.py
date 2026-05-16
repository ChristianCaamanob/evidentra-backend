import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
APP_URL   = os.getenv("APP_URL", "https://web-production-098402.up.railway.app")

def send_reset_email(to_email: str, token: str, teacher_name: str):
    reset_link = f"{APP_URL}/reset-password?token={token}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Evalys — Recuperación de contraseña"
    msg["From"]    = f"Evalys USS <{SMTP_USER}>"
    msg["To"]      = to_email
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#f9f9f9;border-radius:8px;">
      <h2 style="color:#0f4c75;">Evalys — Recuperar contraseña</h2>
      <p>Hola <strong>{teacher_name}</strong>,</p>
      <p>Recibimos una solicitud para restablecer tu contraseña. Haz click en el botón:</p>
      <a href="{reset_link}" style="display:inline-block;margin:16px 0;padding:12px 24px;background:#0f4c75;color:white;border-radius:6px;text-decoration:none;font-weight:bold;">
        Restablecer contraseña
      </a>
      <p style="color:#888;font-size:12px;">Este enlace expira en 15 minutos. Si no solicitaste esto, ignora este mensaje.</p>
      <hr style="border:none;border-top:1px solid #ddd;margin:24px 0;">
      <p style="color:#aaa;font-size:11px;">Universidad San Sebastián · Evalys Plataforma Académica</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
