# -*- coding: utf-8 -*-
"""
SEI - Login -> Controle -> 1º processo -> iframe(ifrArvore)
    -> achar "Gerar PDF" (DOM ou regex no HTML JS)
    -> abrir página de opções
    -> enviar formulário ("Gerar") com hdnFlagGerar=1
    -> capturar URL do iframe de download (acao=exibir_arquivo) e salvar processo.pdf

Como usar (PowerShell / zsh):
  $env:SEI_USER="SEU_LOGIN"
  $env:SEI_PASS="SUA_SENHA"
  $env:SEI_DEBUG="1"   # opcional
  uv run gerar_pdf_clickar_form.py
"""

import os
import re
import sys
import logging
from typing import List, Tuple, Optional, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ===================== LOGGING =====================
LOG_LEVEL = logging.DEBUG if os.environ.get("SEI_DEBUG") else logging.INFO
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sei-gerar-pdf-form")

# ===================== CONFIG =====================
BASE = "https://www.sei.mg.gov.br"
LOGIN_URL = (f"{BASE}/sip/login.php?sigla_orgao_sistema=GOVMG&sigla_sistema=SEI&infra_url=L3NlaS8=")
ORGAO_VALUE = "28"  # SEPLAG

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

RE_PROCESSO = re.compile(r"\b\d{4}\.\s?\d{2}\.\s?\d{7}\s*/\s*\d{4}\s*[-–—-]\s*\d{2}\b", re.I)

# ===================== UTILS =====================
def save_html(path: str, html: str) -> None:
    with open(path, "w", encoding="iso-8859-1") as f:
        f.write(html)
    log.debug(f"HTML salvo: {path} ({len(html)} chars)")

def absolute_to_sei(href: str) -> str:
    if href.startswith("http"):
        return href
    return urljoin(f"{BASE}/sei/", href.lstrip("/"))

def canonizar_processo(txt: str) -> str:
    txt = txt.replace("\xa0", " ")
    txt = re.sub(r"\.\s+", ".", txt)
    txt = re.sub(r"\s*/\s*", "/", txt)
    txt = re.sub(r"\s*-\s*", "-", txt)
    return txt.strip()

# ===================== LOGIN =====================
def login_sei(session: requests.Session, user: str, pwd: str):
    log.info("Abrindo página de login…")
    r = session.get(LOGIN_URL, timeout=30, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    session.cookies.set("SIP_U_GOVMG_SEI", ORGAO_VALUE, domain="sei.mg.gov.br")

    data = {"txtUsuario": user, "pwdSenha": pwd, "selOrgao": ORGAO_VALUE, "hdnAcao": "2", "Acessar": "Acessar"}
    log.info("Enviando POST de login…")
    r = session.post(LOGIN_URL, data=data, timeout=30, headers=HEADERS, allow_redirects=True)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    save_html("login.html", r.text)
    ok = ("Sair" in r.text) or ("Controle de Processos" in r.text)
    log.info("Autenticado com sucesso." if ok else "Login não confirmado no HTML.")
    return ok, r.text

# ===================== CONTROLE =====================
def descobrir_url_controle_do_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "acao=procedimento_controlar" in href:
            return absolute_to_sei(href)
    return None

def abrir_controle(session: requests.Session, html_pos_login: str) -> str:
    url = descobrir_url_controle_do_html(html_pos_login) or f"{BASE}/sei/controlador.php?acao=procedimento_controlar"
    r = session.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    save_html("controle_pagina_1.html", r.text)
    return r.text

def listar_processos_e_links(html_controle: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html_controle, "lxml")
    root = soup.select_one("#divTabelaProcesso") or soup
    anchors = root.select('a[href*="acao=procedimento_trabalhar"], a.processoNaoVisualizado, a.processoVisualizado')

    itens = []
    for a in anchors:
        txt = a.get_text(" ").strip()
        m = RE_PROCESSO.search(txt) or RE_PROCESSO.search(a.get("title","")) or RE_PROCESSO.search(a.get("href",""))
        if not m:
            continue
        proc = canonizar_processo(m.group(0))
        href = a.get("href","")
        if not href:
            continue
        itens.append((proc, absolute_to_sei(href)))

    # dedup preservando ordem
    seen, dedup = set(), []
    for it in itens:
        if it not in seen:
            seen.add(it); dedup.append(it)
    return dedup

# ===================== PROCESSO -> IFRAME =====================
def abrir_primeiro_processo(session: requests.Session, lista: List[Tuple[str,str]]) -> str:
    if not lista:
        raise RuntimeError("Lista de processos vazia — nada para abrir.")
    proc, url = lista[0]
    log.info(f"Abrindo 1º processo: {proc}")
    r = session.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    save_html("processo_primeiro.html", r.text)  # HTML pai (contém iframes)
    return r.text

def extrair_iframe_arvore_src(html_pai: str) -> Optional[str]:
    soup = BeautifulSoup(html_pai, "lxml")
    ifr = soup.select_one("#ifrArvore")
    if not ifr:
        return None
    src = ifr.get("src") or ""
    return absolute_to_sei(src) if src else None

def carregar_iframe_arvore(session: requests.Session, iframe_url: str) -> str:
    log.info(f"Carregando iframe (ifrArvore): {iframe_url}")
    r = session.get(iframe_url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    save_html("processo_iframe.html", r.text)
    return r.text

# ===================== "GERAR PDF": achar link e submeter form =====================
def achar_link_gerar_pdf(html_iframe: str) -> Optional[str]:
    soup = BeautifulSoup(html_iframe, "lxml")
    # 1) DOM direto
    a = (soup.select_one('a[href*="acao=procedimento_gerar_pdf"]')
         or soup.select_one('a:has(img[alt*="Gerar"][alt*="PDF"])')
         or soup.select_one('a[title*="Gerar"][title*="PDF"]'))
    if a and a.get("href"):
        return absolute_to_sei(a["href"])
    # 2) Fallback: regex no HTML (link dentro de string JS)
    m = re.search(r'href="([^"]*acao=procedimento_gerar_pdf[^"]+)"', html_iframe, flags=re.I)
    if m:
        return absolute_to_sei(m.group(1))
    return None

def abrir_pagina_gerar_pdf(session: requests.Session, url_pdf_options: str) -> str:
    log.info(f"Abrindo página de opções do PDF: {url_pdf_options}")
    r = session.get(url_pdf_options, timeout=60, headers=HEADERS)
    r.raise_for_status()
    r.encoding = "iso-8859-1"
    save_html("gerar_pdf_form.html", r.text)
    return r.text

def serializar_formulario(form: BeautifulSoup) -> Dict[str, str]:
    data: Dict[str,str] = {}

    # inputs
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = (inp.get("type") or "").lower()
        val = inp.get("value", "")

        if itype in {"radio", "checkbox"}:
            if inp.has_attr("checked"):
                data[name] = val
        else:
            data[name] = val

    # selects
    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name: 
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        data[name] = opt.get("value","") if opt else ""

    # textareas
    for ta in form.find_all("textarea"):
        name = ta.get("name")
        if not name:
            continue
        data[name] = (ta.text or "")

    # radios sem marcado: escolhe o primeiro (equivalente a "Todos os documentos disponíveis")
    radios_by_name: Dict[str, List[BeautifulSoup]] = {}
    for r in form.find_all("input", {"type": "radio"}):
        n = r.get("name")
        if not n:
            continue
        radios_by_name.setdefault(n, []).append(r)
    for n, radios in radios_by_name.items():
        if n not in data and radios:
            data[n] = radios[0].get("value","")

    return data

def extrair_url_download_do_html(html: str) -> Optional[str]:
    """
    Procura o URL do download que o JS injeta no iframe oculto:
      - <iframe id="ifrDownload" src="...acao=exibir_arquivo...">
      - ou em JS: document.getElementById('ifrDownload').src = '...acao=exibir_arquivo...';
    """
    soup = BeautifulSoup(html, "lxml")
    ifr = soup.select_one("#ifrDownload")
    if ifr:
        src = (ifr.get("src") or "").strip()
        if src and "acao=exibir_arquivo" in src:
            return absolute_to_sei(src)

    # procurar em JavaScript/HTML bruto
    m = re.search(r"['\"]([^'\"]*acao=exibir_arquivo[^'\"]+)['\"]", html, flags=re.I)
    if m:
        return absolute_to_sei(m.group(1))
    return None

def baixar_por_url(session: requests.Session, url: str, out_path: str = "processo.pdf") -> bool:
    headers = dict(HEADERS)
    headers["Accept"] = "application/pdf, */*;q=0.8"
    log.info(f"Baixando arquivo: {url}")
    r = session.get(url, timeout=120, headers=headers, allow_redirects=True, stream=True)
    ctype = (r.headers.get("Content-Type") or "").lower()
    disp  = (r.headers.get("Content-Disposition") or "")
    if "application/pdf" in ctype or ".pdf" in disp.lower():
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        log.info(f"PDF salvo: {out_path}")
        return True
    # fallback: salvar HTML se não for PDF
    try:
        html = r.text
        save_html("processo_pdf_intermediario.html", html)
        log.warning("Download não retornou PDF. Salvei 'processo_pdf_intermediario.html' para inspeção.")
    except Exception:
        log.warning("Resposta do download não é texto nem PDF; verifique cabeçalhos/redirects.")
    return False

def enviar_form_gerar(session: requests.Session, html_form: str, referer_url: str) -> None:
    soup = BeautifulSoup(html_form, "lxml")

    # encontrar o formulário correto (o da tela "Gerar Arquivo PDF do Processo")
    form = None
    for f in soup.find_all("form"):
        act = (f.get("action") or "")
        btns = " ".join(b.get("value","") for b in f.find_all("input", {"type":"submit"}))
        if "procedimento_gerar_pdf" in act or "Gerar" in btns:
            form = f; break
    if not form:
        forms = soup.find_all("form")
        if not forms:
            save_html("processo_pdf_intermediario.html", html_form)
            raise RuntimeError("Não encontrei formulário na página de opções — salvei gerar_pdf_form.html.")
        form = forms[0]

    action = form.get("action") or ""
    method = (form.get("method") or "post").lower()
    url_action = absolute_to_sei(action)

    data = serializar_formulario(form)

    # >>> Ajustes (mesmo que o JS faria):
    data["hdnFlagGerar"] = "1"          # backend só gera com essa flag
    data.setdefault("rdoTipo", "T")     # "Todos os documentos disponíveis"
    data.setdefault("btnGerar", "Gerar")

    headers = dict(HEADERS)
    headers["Referer"] = referer_url
    headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"

    log.debug(f"Enviando formulário ({method.upper()}) para {url_action} com campos: {list(data.keys())}")

    if method == "post":
        r = session.post(url_action, data=data, timeout=120, headers=headers, allow_redirects=True)
    else:
        r = session.get(url_action, params=data, timeout=120, headers=headers, allow_redirects=True)

    r.raise_for_status()
    r.encoding = "iso-8859-1"
    save_html("processo_pdf_intermediario.html", r.text)

    # <<< NOVO PASSO >>> capturar URL do iframe de download e baixar
    url_download = extrair_url_download_do_html(r.text)
    if url_download:
        ok = baixar_por_url(session, url_download, out_path="processo.pdf")
        if not ok:
            log.warning("Falha ao baixar via URL do iframe; veja processo_pdf_intermediario.html.")
    else:
        log.warning("Não encontrei URL de download (acao=exibir_arquivo) na resposta. Veja processo_pdf_intermediario.html.")

# ===================== MAIN =====================
def main():
    user = os.environ.get("SEI_USER")
    pwd  = os.environ.get("SEI_PASS")
    if not user or not pwd:
        log.error("Defina SEI_USER e SEI_PASS nas variáveis de ambiente.")
        sys.exit(1)

    with requests.Session() as s:
        s.headers.update(HEADERS)

        ok, html_login = login_sei(s, user, pwd)
        if not ok:
            log.error("Falha no login — veja login.html.")
            sys.exit(2)

        html_controle = abrir_controle(s, html_login)
        processos = listar_processos_e_links(html_controle)
        log.info(f"Total de processos listados: {len(processos)}")

        html_pai = abrir_primeiro_processo(s, processos)
        iframe_url = extrair_iframe_arvore_src(html_pai)
        if not iframe_url:
            log.error("Não encontrei o iframe 'ifrArvore' no HTML pai.")
            sys.exit(3)

        html_iframe = carregar_iframe_arvore(s, iframe_url)

        link_pdf = achar_link_gerar_pdf(html_iframe)
        if not link_pdf:
            log.error("Não encontrei link 'procedimento_gerar_pdf' (DOM/JS). Veja processo_iframe.html.")
            sys.exit(4)

        # 1) Abre a página de opções (a do print) e salva
        html_form = abrir_pagina_gerar_pdf(s, link_pdf)

        # 2) Envia o formulário como se clicasse em "Gerar" e baixa via iframe de download
        enviar_form_gerar(s, html_form, referer_url=link_pdf)

if __name__ == "__main__":
    main()
