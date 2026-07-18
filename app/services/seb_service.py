"""
LV9 · Bloqueo real con Safe Exam Browser (SEB) para pruebas de alto impacto.

La web NO puede bloquear screenshots ni encerrar el equipo; SEB (cliente kiosco gratuito y
open-source, Win/Mac/iPad) sí. La estrategia:
  1) Evalys genera un archivo de configuración .seb de la sala (URL de inicio + restricciones).
  2) El alumno instala SEB una vez y abre ese .seb → SEB arranca bloqueado en la sala.
  3) SEB envía en cada petición cabeceras de verificación; Evalys comprueba que la petición
     REALMENTE viene de SEB (un navegador normal nunca las envía) y, si no, rechaza la sala.

Verificación (v1, honesta): exige User-Agent de SEB + presencia de la cabecera de hash (que un
navegador común no manda). El match EXACTO del hash contra la config key depende del algoritmo/
versión de SEB y conviene validarlo con un cliente SEB real; aquí se calcula y se reporta como
señal (hash_ok) pero el bloqueo base no depende de él, para no dejar fuera a un SEB legítimo.
"""
from __future__ import annotations

import hashlib
import plistlib
from urllib.parse import urlparse


def _settings(join_url: str, quit_pwd: str) -> dict:
    host = urlparse(join_url).netloc or ""
    quit_hash = hashlib.sha256((quit_pwd or "").encode("utf-8")).hexdigest()
    return {
        "startURL": join_url,
        "sendBrowserExamKey": True,           # que SEB mande las cabeceras de verificación
        "allowQuit": True,
        "hashedQuitPassword": quit_hash,       # el alumno no puede salir sin la clave del docente
        "browserWindowAllowReload": True,
        "showReloadButton": True,
        "enableRightMouse": False,             # sin clic derecho
        "hideBrowserWindowToolbar": True,
        "showMenuBar": False,
        "showTaskBar": False,
        "allowSpellCheck": False,
        "allowDictionaryLookup": False,
        "allowPrint": False,                   # sin imprimir/guardar como PDF
        "allowDownUploads": False,
        "allowDeveloperConsole": False,
        "URLFilterEnable": True,               # solo se permite el dominio de la sala
        "URLFilterEnableContentFilter": False,
        "whitelistURLFilter": f"{host}/*",
        "blacklistURLFilter": "",
        "examSessionClearCookiesOnStart": True,
        "restartExamUseStartURL": True,
        "createNewDesktop": True,              # kiosco en Windows
        "enableLogging": False,
    }


def generar_config(join_url: str, quit_pwd: str = "evalys") -> tuple[bytes, str]:
    """Devuelve (bytes del .seb en plist XML, config_key sha256). El .seb va SIN cifrar (SEB
    pedirá confirmar la fuente); simple y suficiente para el piloto."""
    s = _settings(join_url, quit_pwd)
    xml = plistlib.dumps(s, fmt=plistlib.FMT_XML, sort_keys=True)
    # config key ≈ sha256 del plist canónico (ordenado). Señal de verificación, no gate duro.
    key = hashlib.sha256(xml).hexdigest()
    return xml, key


def verificar(headers, url: str, config_key: str | None) -> dict:
    """headers: objeto tipo dict/Headers (case-insensitive). Determina si la petición viene de SEB."""
    def g(k):
        try:
            return headers.get(k) or headers.get(k.title()) or headers.get(k.upper()) or ""
        except Exception:
            return ""
    ua = g("user-agent")
    es_seb = ("SEB" in ua) or ("SafeExamBrowser" in ua)
    hash_hdr = g("x-safeexambrowser-configkeyhash") or g("x-safeexambrowser-requesthash")
    hdr_present = bool(hash_hdr)
    hash_ok = None
    if config_key and hash_hdr:
        esperado = hashlib.sha256((str(url) + config_key).encode("utf-8")).hexdigest()
        hash_ok = (esperado.lower() == str(hash_hdr).lower())
    # Gate base: UA de SEB + cabecera de hash presente (un navegador normal no las envía).
    return {"seb": bool(es_seb and hdr_present), "ua_seb": es_seb,
            "headers_present": hdr_present, "hash_ok": hash_ok}
