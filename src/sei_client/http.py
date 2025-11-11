"""Funções auxiliares para lidar com sessões HTTP e URLs do SEI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests

from .config import Settings

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

log = logging.getLogger(__name__)


def create_session(settings: Settings) -> requests.Session:
    """Inicializa uma sessão HTTP com cabeçalhos e cookie do órgão configurados."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if settings.orgao_value:
        session.cookies.set("SIP_U_GOVMG_SEI", settings.orgao_value, domain="sei.mg.gov.br")
    return session


def absolute_to_sei(settings: Settings, href: str) -> str:
    """Converte um `href` relativo em URL absoluta para o domínio do SEI."""
    if href.startswith("http"):
        return href
    return urljoin(f"{settings.base_url}/sei/", href.lstrip("/"))


def save_html(settings: Settings, path: Path, html: str) -> None:
    """Salva HTML em disco quando o modo de depuração estiver ativado."""
    if not settings.save_debug_html:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="iso-8859-1")
        log.debug("HTML salvo: %s (%s chars)", path, len(html))
    except Exception as exc:  # pragma: no cover - apenas log
        log.warning("Erro ao salvar HTML %s: %s", path, exc)

