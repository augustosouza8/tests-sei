# -*- coding: utf-8 -*-
"""
SEI scraper: login + extração SOMENTE dos processos com a classe 'processoNaoVisualizado',
com regex tolerante a espaços (ex.: "1500. 01. 0310980/2025-88").

Como usar (PowerShell / macOS zsh):
  # defina as credenciais em variáveis de ambiente:
  $env:SEI_USER="SEU_LOGIN"
  $env:SEI_PASS="SUA_SENHA"
  # (opcional) logs detalhados:
  $env:SEI_DEBUG="1"
  uv run login_sei.py
"""

import os
import re
import sys
import time
import logging
import unicodedata
from typing import Iterable, Set, Tuple, Optional, List, Dict

import requests
from bs4 import BeautifulSoup


# ===================== LOGGING / DEBUG =====================
LOG_LEVEL = logging.DEBUG if os.environ.get("SEI_DEBUG") else logging.INFO
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sei-scraper")


# ===================== CONFIG BÁSICA =====================
BASE = "https://www.sei.mg.gov.br"
LOGIN_URL = (
    f"{BASE}/sip/login.php"
    "?sigla_orgao_sistema=GOVMG"
    "&sigla_sistema=SEI"
    "&infra_url=L3NlaS8="  # "/sei/"
)
ORGAO_VALUE = "28"  # SEPLAG

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Tela de controle (fallbacks)
CONTROLE_URLS = [
    f"{BASE}/sei/controlador.php?acao=procedimento_controlar",
    f"{BASE}/sei/controlador.php?acao=procedimento_controlar&acao_origem=procedimento_controlar",
    f"{BASE}/sei/controlador.php?acao=procedimento_controlar&infra_sistema=100000100",
]

# Classe alvo (somente não visualizados)
ALVOS_CLASSES = ["processoNaoVisualizado"]

# ========= Regex para número de processo (tolerante a espaços) =========
# Aceita espaços opcionais após os pontos e ao redor de "/" e do hífen:
RE_PROCESSO_SPACED = re.compile(
    r"\b\d{4}\.\s?\d{2}\.\s?\d{7}\s*/\s*\d{4}\s*[-–—-]\s*\d{2}\b"
)
# Útil para depuração (ver “quase-processos”)
RE_QUASE_PROCESSO  = re.compile(r"\d{4}\.\s?\d{2}\.\s?\d{7}\s*/\s*\d{4}.?")


# ===================== UTILS =====================
DASHES = {"\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"}  # hífens parecidos
ZWS    = {"\u200b", "\u200c", "\u200d", "\ufeff"}                      # zero-width / BOM

def _save_html(path: str, html: str) -> None:
    try:
        with open(path, "w", encoding="iso-8859-1") as f:
            f.write(html)
        log.debug(f"HTML salvo: {path} ({len(html)} chars)")
    except Exception as e:
        log.warning(f"Falha ao salvar {path}: {e}")

def _cookie_names(s: requests.Session) -> str:
    return ", ".join({c.name for c in s.cookies}) or "(sem cookies)"

def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\xa0", " ")  # NBSP
    for d in DASHES:
        s = s.replace(d, "-")
    for z in ZWS:
        s = s.replace(z, "")
    return s

def _canonizar_processo(p: str) -> str:
    """Remove espaços após os pontos para padronizar: '1500. 01. 0310980/2025-88' -> '1500.01.0310980/2025-88'."""
    p = _normalize_text(p)
    p = re.sub(r"\.\s+", ".", p)  # ponto+espaços -> ponto
    p = re.sub(r"\s*/\s*", "/", p)  # ao redor da barra
    p = re.sub(r"\s*-\s*", "-", p)  # ao redor do hífen
    return p.strip()

def _extrair_processos_de_texto(texto: str) -> Set[str]:
    texto = _normalize_text(texto)
    ach = set(RE_PROCESSO_SPACED.findall(texto))
    if not ach:
        # ajuda: tentar ver “quase-processos” para debug
        quase = RE_QUASE_PROCESSO.findall(texto)
        if quase[:3]:
            log.debug("[texto] quase-processos (amostra): " + ", ".join(quase[:3]))
    # canoniza
    return { _canonizar_processo(p) for p in ach }


# ===================== LOGIN =====================
def login_sei(session: requests.Session, user: str, pwd: str) -> Tuple[bool, str]:
    log.info("Abrindo página de login…")
    r = session.get(LOGIN_URL, timeout=30, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    log.debug(f"Cookies após GET login: {_cookie_names(session)}")

    # Cookie de órgão que o front costuma setar via JS
    session.cookies.set("SIP_U_GOVMG_SEI", ORGAO_VALUE, domain="sei.mg.gov.br")

    data = {
        "txtUsuario": user,
        "pwdSenha":  pwd,
        "selOrgao":  ORGAO_VALUE,
        "hdnAcao":   "2",  # acaoLogin(2)
        "Acessar":   "Acessar",
    }
    log.info("Enviando POST de login…")
    r = session.post(LOGIN_URL, data=data, timeout=30, headers=HEADERS, allow_redirects=True)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    _save_html("login.html", r.text)

    ok = ("Sair" in r.text) or ("Controle de Processos" in r.text)
    log.info("Autenticado com sucesso." if ok else "Login não confirmado no HTML.")
    return ok, r.text


# ===================== DESCOBRIR URL CONTROLE =====================
def descobrir_url_controle_do_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "acao=procedimento_controlar" in href:
            if href.startswith("controlador.php"):
                url = f"{BASE}/sei/{href}"
            elif href.startswith("?"):
                url = f"{BASE}/sei/controlador.php{href}"
            elif href.startswith("http"):
                url = href
            else:
                url = f"{BASE}/sei/{href.lstrip('/')}"
            log.info(f"URL do Controle encontrada no HTML: {url}")
            return url
    return None

def buscar_primeira_pagina_controle(session: requests.Session, html_pos_login: str) -> Tuple[str, str]:
    url = descobrir_url_controle_do_html(html_pos_login)
    if url:
        resp = session.get(url, timeout=30, headers=HEADERS, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = "iso-8859-1"
        _save_html("controle_pagina_1.html", resp.text)
        return url, resp.text

    # Fallbacks
    last = None
    for u in CONTROLE_URLS:
        resp = session.get(u, timeout=30, headers=HEADERS, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = "iso-8859-1"
        _save_html("controle_pagina_1.html", resp.text)
        if ("divTabelaProcesso" in resp.text) or ("Controle de Processos" in resp.text):
            return u, resp.text
        last = (u, resp.text)
    u, t = last
    return u, t


# ===================== EXTRAÇÃO FILTRADA POR CLASSE =====================
def _contar_por_classe(soup: BeautifulSoup, classes: List[str]) -> Dict[str, int]:
    root = soup.select_one("#divTabelaProcesso") or soup
    counts = {}
    # também reporta 'processoVisualizado' para comparação
    for cls in classes + ["processoVisualizado"]:
        counts[cls] = len(root.select(f".{cls}"))
    return counts

def _targets_por_classes(soup: BeautifulSoup, classes: List[str]) -> List[BeautifulSoup]:
    root = soup.select_one("#divTabelaProcesso") or soup
    out = []
    for cls in classes:
        out.extend(root.select(f".{cls}"))
    # dedup preservando ordem
    seen, dedup = set(), []
    for el in out:
        if id(el) not in seen:
            seen.add(id(el))
            dedup.append(el)
    log.debug(f"[classes={classes}] elementos alvo: {len(dedup)}")
    return dedup

def extrair_processos_por_classes(html: str, classes: List[str]) -> Set[str]:
    soup = BeautifulSoup(html, "lxml")

    counts = _contar_por_classe(soup, classes)
    log.info("Resumo por classe (na página atual): " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    processos: Set[str] = set()
    alvos = _targets_por_classes(soup, classes)

    for idx, el in enumerate(alvos, 1):
        # 1) texto do próprio elemento
        processos |= _extrair_processos_de_texto(el.get_text(" "))

        # 2) atributos do próprio elemento
        for attr in ("title", "href", "onclick", "data-title", "data-tooltip"):
            v = el.get(attr)
            if v and isinstance(v, str):
                processos |= _extrair_processos_de_texto(v)

        # 3) filhos comuns que carregam o número
        for a in el.find_all(["a", "span", "div"], recursive=True):
            processos |= _extrair_processos_de_texto(a.get_text(" "))
            for attr in ("title", "href", "onclick", "data-title", "data-tooltip"):
                v2 = a.get(attr)
                if v2 and isinstance(v2, str):
                    processos |= _extrair_processos_de_texto(v2)

        # depuração opcional
        if LOG_LEVEL == logging.DEBUG and idx <= 3:
            txt = _normalize_text(el.get_text(" "))
            quase = RE_QUASE_PROCESSO.findall(txt)
            if quase:
                log.debug(f"[amostra alvo#{idx}] quase-processos: {', '.join(quase[:3])}")

    log.info(f"[classes={classes}] processos extraídos: {len(processos)}")
    if processos:
        log.debug("Amostra (10): " + ", ".join(sorted(processos)[:10]))
    return processos


def encontrar_links_paginacao(html: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "lxml")
    pagers = soup.select('[id*="AreaPaginacao"] a, .paginacao a, a')
    links = []
    for a in pagers:
        txt = (a.get_text() or "").strip().lower()
        if txt in {"próxima", "proxima", ">", "»", "avançar", "avancar"}:
            href = a.get("href")
            if not href:
                continue
            if href.startswith("controlador.php"):
                links.append(f"{BASE}/sei/{href}")
            elif href.startswith("?"):
                links.append(f"{BASE}/sei/controlador.php{href}")
            elif href.startswith("http"):
                links.append(href)
    log.debug(f"Links de paginação encontrados: {len(links)}")
    for l in links:
        log.debug(f"  → {l}")
    return links


def coletar_processos_filtrados(session: requests.Session, html_pos_login: str, classes: List[str]) -> Set[str]:
    # 1) Pós-login
    log.info("Tentando extrair (classes alvo) do HTML pós-login…")
    total = extrair_processos_por_classes(html_pos_login, classes)
    if total:
        log.info("Já encontrei processos com as classes alvo no HTML pós-login.")
        return total

    # 2) Tela de controle
    url, html = buscar_primeira_pagina_controle(session, html_pos_login)
    log.info(f"Página de controle inicial: {url} (len={len(html)})")
    total |= extrair_processos_por_classes(html, classes)
    visitados = {url}
    pagina = 1

    # 3) Paginação (se houver)
    while True:
        prox_links = [l for l in encontrar_links_paginacao(html) if l not in visitados]
        if not prox_links:
            log.info("Sem próxima página — fim da coleta.")
            break

        url = prox_links[0]
        log.info(f"Indo para próxima página: {url}")
        resp = session.get(url, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        resp.encoding = "iso-8859-1"
        pagina += 1
        html = resp.text
        _save_html(f"controle_pagina_{pagina}.html", html)
        total |= extrair_processos_por_classes(html, classes)
        visitados.add(url)
        time.sleep(0.4)  # gentil com o servidor

    return total


# ===================== MAIN =====================
def main():
    user = "07300016600"
    pwd  = "Au2596390"

    with requests.Session() as s:
        s.headers.update(HEADERS)

        ok, html_login = login_sei(s, user, pwd)
        if not ok:
            log.error("Falha no login — verifique credenciais/fluxo. Veja login.html.")
            sys.exit(2)

        procesos_set = coletar_processos_filtrados(s, html_login, ALVOS_CLASSES)
        processos_ordenados = sorted(procesos_set)

        log.info("=" * 60)
        log.info(f"TOTAL ({'+'.join(ALVOS_CLASSES)}) ENCONTRADOS: {len(processos_ordenados)}")
        for p in processos_ordenados[:30]:
            log.info(f"  • {p}")
        log.info("=" * 60)

        print(processos_ordenados)

        # (Opcional) salvar CSV:
        import csv
        with open(f"processos_{'+'.join(ALVOS_CLASSES)}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["processo"])
            for p in processos_ordenados: w.writerow([p])

if __name__ == "__main__":
    main()
