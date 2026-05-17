import urllib.request
import urllib.error
import json
import os

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
APP_URL = os.getenv("APP_URL", "https://web-production-098402.up.railway.app")

def send_reset_email(to_email: str, token: str, teacher_name: str):
    reset_link = f"{APP_URL}/reset-password?token={token}"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#f9f9f9;border-radius:8px;">
      <h2 style="color:#0f4c75;">Evalys — Recuperar contraseña</h2>
      <p>Hola <strong>{teacher_name}</strong>,</p>
      <p>Recibimos una solicitud para restablecer tu contraseña. Haz click en el botón:</p>
      <a href="{reset_link}" style="display:inline-block;margin:16px 0;padding:12px 24px;background:#0F8B8D;color:white;border-radius:6px;text-decoration:none;font-weight:bold;">
        Restablecer contraseña
      </a>
      <p style="color:#888;font-size:12px;">Este enlace expira en 15 minutos. Si no solicitaste esto, ignora este mensaje.</p>
      <hr style="border:none;border-top:1px solid #ddd;margin:24px 0;">
      <p style="color:#aaa;font-size:11px;">Universidad San Sebastián · Evalys Plataforma Académica</p>
    </div>
    """
    payload = json.dumps({
        "from": "Evalys USS <onboarding@resend.dev>",
        "to": ["mispelis2020@gmail.com"],
        "subject": "Evalys — Recuperación de contraseña",
        "html": html
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())
