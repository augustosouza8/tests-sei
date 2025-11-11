"""Fluxos de autenticação e acesso às páginas iniciais do SEI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .exceptions import SEILoginError, SEIProcessoError
from .http import DEFAULT_HEADERS, absolute_to_sei, save_html

log = logging.getLogger(__name__)


def login_sei(session: requests.Session, settings: Settings, user: str, pwd: str) -> tuple[bool, str]:
    """Autentica o usuário no SEI e devolve o HTML resultante da página pós-login."""
    if not user or not pwd:
        raise SEILoginError("Usuário e senha devem ser fornecidos")

    try:
        log.info("Abrindo página de login…")
        response = session.get(settings.login_url, timeout=30, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        response.encoding = "iso-8859-1"

        session.cookies.set("SIP_U_GOVMG_SEI", settings.orgao_value, domain="sei.mg.gov.br")

        data = {
            "txtUsuario": user,
            "pwdSenha": pwd,
            "selOrgao": settings.orgao_value,
            "hdnAcao": "2",
            "Acessar": "Acessar",
        }

        log.info("Enviando POST de login…")
        response = session.post(settings.login_url, data=data, timeout=30, headers=DEFAULT_HEADERS, allow_redirects=True)
        response.raise_for_status()
        response.encoding = "iso-8859-1"

        save_html(settings, settings.data_dir / "debug" / "login.html", response.text)

        ok = ("Sair" in response.text) or ("Controle de Processos" in response.text)
        if ok:
            cookies_ok = any("SIP" in cookie.name for cookie in session.cookies)
            if not cookies_ok:
                log.warning("Login aparentemente bem-sucedido, mas cookies de sessão não encontrados")

        if not ok:
            lowered = response.text.lower()
            if "usuário ou senha" in lowered or "inval" in lowered:
                raise SEILoginError("Credenciais inválidas")
            if "bloqueado" in lowered or "bloqueio" in lowered:
                raise SEILoginError("Conta bloqueada")
            raise SEILoginError("Login não confirmado - verifique credenciais")

        log.info("Autenticado com sucesso.")
        return True, response.text

    except requests.RequestException as exc:
        raise SEILoginError(f"Erro de rede durante login: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, SEILoginError):
            raise
        raise SEILoginError(f"Erro inesperado durante login: {exc}") from exc


def descobrir_url_controle_do_html(settings: Settings, html: str) -> Optional[str]:
    """Localiza a URL absoluta da área de controle a partir do HTML pós-login."""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if "acao=procedimento_controlar" in href:
                return absolute_to_sei(settings, href)
        return None
    except Exception as exc:
        log.warning("Erro ao descobrir URL de controle: %s", exc)
        return None


def abrir_controle(session: requests.Session, settings: Settings, html_pos_login: str) -> tuple[str, str]:
    """Abre a página de controle de processos e devolve o HTML e a URL acessada."""
    try:
        url = descobrir_url_controle_do_html(settings, html_pos_login) or f"{settings.base_url}/sei/controlador.php?acao=procedimento_controlar"
        log.info("Acessando controle de processos: %s", url)
        response = session.get(url, timeout=30, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        response.encoding = "iso-8859-1"
        save_html(settings, settings.data_dir / "debug" / "controle_pagina_1.html", response.text)
        return response.text, url
    except requests.RequestException as exc:
        raise SEIProcessoError(f"Erro ao acessar controle de processos: {exc}") from exc

