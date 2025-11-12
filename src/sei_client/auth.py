"""Fluxos de autenticação e acesso às páginas iniciais do SEI."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

from .config import Settings
from .exceptions import SEILoginError, SEIProcessoError
from .http import DEFAULT_HEADERS, absolute_to_sei, save_html

log = logging.getLogger(__name__)

RE_ONCLICK_REDIRECT = re.compile(r"window\.location\.href='(?P<url>[^']+)'")


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


def obter_unidade_atual(settings: Settings, html_controle: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai a unidade SEI atualmente selecionada e a URL de troca, se disponível."""
    try:
        soup = BeautifulSoup(html_controle, "lxml")
        anchor = soup.select_one("#lnkInfraUnidade")
        if not anchor or not isinstance(anchor, Tag):
            log.debug("Elemento #lnkInfraUnidade não encontrado no HTML do controle.")
            return None, None

        nome_unidade = anchor.get_text(" ", strip=True) or None
        onclick = anchor.get("onclick") or ""
        url_troca: Optional[str] = None

        match = RE_ONCLICK_REDIRECT.search(onclick)
        if match:
            url_relativa = match.group("url")
            url_troca = absolute_to_sei(settings, url_relativa)
        else:
            log.debug("Não foi possível identificar URL de troca da unidade no atributo onclick.")

        return nome_unidade, url_troca
    except Exception as exc:  # pragma: no cover - fallback defensivo
        log.warning("Falha ao determinar unidade SEI atual: %s", exc)
        return None, None


def carregar_pagina_selecao_unidades(
    session: requests.Session, settings: Settings, url_troca: str
) -> str:
    """Carrega a página HTML que lista todas as unidades SEI disponíveis para o usuário."""
    try:
        log.info("Carregando página de seleção de unidades: %s", url_troca)
        response = session.get(url_troca, timeout=30, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        response.encoding = "iso-8859-1"
        save_html(settings, settings.data_dir / "debug" / "selecao_unidades.html", response.text)
        return response.text
    except requests.RequestException as exc:
        raise SEIProcessoError(f"Erro ao carregar página de seleção de unidades: {exc}") from exc


def selecionar_unidade_sei(
    session: requests.Session,
    settings: Settings,
    html_selecao: str,
    unidade_desejada: str,
    url_troca_origem: str,
) -> tuple[bool, Optional[str]]:
    """
    Busca e seleciona a unidade SEI desejada na página de seleção.

    Args:
        session: Sessão HTTP ativa
        settings: Configurações do cliente
        html_selecao: HTML da página de seleção de unidades
        unidade_desejada: Nome da unidade SEI a selecionar (ex: "SEPLAG/AUTOMATIZAMG")
        url_troca_origem: URL original que levou à página de seleção (para referer)

    Returns:
        Tupla (sucesso, html_resultante): True se a unidade foi selecionada com sucesso,
        False caso contrário. O HTML resultante pode ser None se houver erro.
    """
    try:
        soup = BeautifulSoup(html_selecao, "lxml")
        # A tabela pode ter ID começando com infraTable ou apenas a classe infraTable
        tabela = soup.select_one("table[id^='infraTable'], table.infraTable")
        if not tabela:
            # Tenta encontrar qualquer tabela com caption contendo "Unidades"
            tabelas = soup.find_all("table")
            for tab in tabelas:
                caption = tab.find("caption")
                if caption and "unidade" in caption.get_text(" ", strip=True).lower():
                    tabela = tab
                    break
        
        if not tabela:
            log.warning("Tabela de unidades não encontrada na página de seleção.")
            # Salva o HTML para debug mesmo em caso de erro
            save_html(settings, settings.data_dir / "debug" / "selecao_unidades_debug.html", html_selecao)
            return False, None

        log.debug("Tabela de unidades encontrada com sucesso.")
        # Busca pela unidade desejada nas linhas da tabela
        # As linhas podem estar em tbody ou diretamente na tabela
        linhas = tabela.select("tbody tr") or tabela.select("tr")
        # Remove a linha de cabeçalho se existir
        linhas = [linha for linha in linhas if isinstance(linha, Tag) and linha.select("th") == []]
        unidade_desejada_normalizada = unidade_desejada.strip().upper()
        
        log.debug("Buscando unidade: '%s' (normalizada: '%s')", unidade_desejada, unidade_desejada_normalizada)
        log.debug("Total de linhas encontradas na tabela: %s", len(linhas))

        unidades_encontradas: list[str] = []
        for linha in linhas:
            if not isinstance(linha, Tag):
                continue

            # Procura pelo texto da unidade na segunda coluna (td[1])
            celulas = linha.select("td")
            if len(celulas) < 2:
                continue

            texto_unidade = celulas[1].get_text(" ", strip=True)
            texto_unidade_normalizado = texto_unidade.strip().upper()
            unidades_encontradas.append(texto_unidade)
            
            # Comparação mais robusta: normaliza ambos os lados e remove espaços extras
            # Também remove caracteres de controle e normaliza espaços múltiplos
            texto_limpo = re.sub(r'\s+', ' ', texto_unidade_normalizado).strip()
            desejo_limpo = re.sub(r'\s+', ' ', unidade_desejada_normalizada).strip()
            
            log.debug("Comparando: '%s' (limpo: '%s') com '%s' (limpo: '%s')", 
                     texto_unidade, texto_limpo, unidade_desejada, desejo_limpo)
            
            if texto_limpo == desejo_limpo:
                # Encontrou a unidade! Procura o radio button correspondente
                radio = linha.select_one('input[type="radio"][name="chkInfraItem"]')
                if not radio or not isinstance(radio, Tag):
                    log.warning("Radio button não encontrado para a unidade %s", unidade_desejada)
                    continue

                valor_unidade = radio.get("value")
                if not valor_unidade:
                    log.warning("Valor do radio button não encontrado para a unidade %s", unidade_desejada)
                    continue

                # Encontra o formulário (deve ser frmInfraSelecaoUnidade)
                form = soup.select_one("form#frmInfraSelecaoUnidade, form")
                if not form or not isinstance(form, Tag):
                    log.warning("Formulário não encontrado na página de seleção.")
                    return False, None

                from .dom import serializar_formulario

                data = serializar_formulario(form)
                # O método correto é usar selInfraUnidades (conforme função JavaScript selecionarUnidade)
                data["selInfraUnidades"] = valor_unidade
                # Também marca o radio button como selecionado
                data["chkInfraItem"] = valor_unidade

                action = form.get("action", "")
                url_action = absolute_to_sei(settings, action) if action else url_troca_origem

                headers = dict(DEFAULT_HEADERS)
                headers["Referer"] = url_troca_origem
                headers["Content-Type"] = "application/x-www-form-urlencoded"

                log.info("Selecionando unidade SEI: %s (ID: %s)", unidade_desejada, valor_unidade)
                response = session.post(url_action, data=data, headers=headers, timeout=30, allow_redirects=True)
                response.raise_for_status()
                response.encoding = "iso-8859-1"

                save_html(settings, settings.data_dir / "debug" / "troca_unidade_resultado.html", response.text)

                # Verifica se a troca foi bem-sucedida checando se voltamos para o controle
                if "Controle de Processos" in response.text or "procedimento_controlar" in response.text:
                    log.info("Unidade SEI alterada com sucesso para: %s", unidade_desejada)
                    return True, response.text
                else:
                    log.warning("Resposta da troca de unidade não parece ter sido bem-sucedida.")
                    return False, response.text

        log.warning("Unidade SEI '%s' não encontrada na lista de unidades disponíveis.", unidade_desejada)
        log.debug("Unidades disponíveis encontradas: %s", unidades_encontradas)
        return False, None

    except requests.RequestException as exc:
        raise SEIProcessoError(f"Erro de rede ao selecionar unidade SEI: {exc}") from exc
    except Exception as exc:
        log.error("Erro inesperado ao selecionar unidade SEI: %s", exc, exc_info=True)
        return False, None

