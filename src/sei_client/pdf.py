"""Operações relacionadas à geração e download de PDFs dentro do SEI."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup, Tag

from .config import Settings
from .documents import carregar_iframe_arvore, extrair_iframe_arvore_src
from .dom import serializar_formulario
from .exceptions import SEIPDFError, SEIProcessoError
from .http import DEFAULT_HEADERS, absolute_to_sei, save_html
from .models import PDFDownloadOptions, PDFDownloadResult, Processo
from .processes import abrir_processo

log = logging.getLogger(__name__)


def _sanitize_filename(value: str, default: str = "arquivo") -> str:
    """Gera um nome de arquivo seguro a partir dos dados do processo."""
    import re

    if not value:
        return default
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
    safe = safe.strip("_")
    return safe or default


def achar_link_gerar_pdf(settings: Settings, html_iframe: str) -> Optional[str]:
    """Procura o link de ação para gerar PDF dentro da árvore de documentos."""
    try:
        soup = BeautifulSoup(html_iframe, "lxml")
        link = (
            soup.select_one('a[href*="acao=procedimento_gerar_pdf"]')
            or soup.select_one('a:has(img[alt*="Gerar"][alt*="PDF"])')
            or soup.select_one('a[title*="Gerar"][title*="PDF"]')
        )
        if link and isinstance(link, Tag):
            href = link.get("href")
            if isinstance(href, str) and href:
                return absolute_to_sei(settings, href)
        match = None
        import re

        match = re.search(r'href="([^"]*acao=procedimento_gerar_pdf[^"]+)"', html_iframe, flags=re.I)
        if match:
            return absolute_to_sei(settings, match.group(1))
        return None
    except Exception as exc:
        log.warning("Erro ao procurar link de gerar PDF: %s", exc)
        return None


def abrir_pagina_gerar_pdf(session: requests.Session, settings: Settings, url_pdf_options: str) -> str:
    """Carrega a página intermediária com configurações de geração de PDF."""
    try:
        log.info("Abrindo página de opções do PDF: %s", url_pdf_options)
        response = session.get(url_pdf_options, timeout=60, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        response.encoding = "iso-8859-1"
        save_html(settings, settings.data_dir / "debug" / "gerar_pdf_form.html", response.text)
        return response.text
    except requests.RequestException as exc:
        raise SEIPDFError(f"Erro ao abrir página de opções PDF: {exc}") from exc


def extrair_url_download_do_html(settings: Settings, html: str) -> Optional[str]:
    """Identifica a URL final usada pelo SEI para disponibilizar o PDF."""
    try:
        soup = BeautifulSoup(html, "lxml")
        iframe = soup.select_one("#ifrDownload")
        if iframe and isinstance(iframe, Tag):
            src = iframe.get("src")
            if isinstance(src, str) and "acao=exibir_arquivo" in src:
                return absolute_to_sei(settings, src)
        import re

        match = re.search(r"['\"]([^'\"]*acao=exibir_arquivo[^'\"]+)['\"]", html, flags=re.I)
        if match:
            return absolute_to_sei(settings, match.group(1))
        return None
    except Exception as exc:
        log.warning("Erro ao extrair URL de download: %s", exc)
        return None


def extrair_mensagem_erro_pdf(html: str) -> Optional[str]:
    """Retorna mensagens de erro apresentadas pelo SEI durante a geração de PDF."""
    try:
        soup = BeautifulSoup(html, "lxml")
        alert = soup.select_one("#divInfraMensagens .alert")
        if alert:
            return alert.get_text(" ", strip=True)
    except Exception:
        pass
    return None


def baixar_por_url(
    session: requests.Session,
    settings: Settings,
    url: str,
    processo: Optional[Processo] = None,
    diretorio_saida: Optional[Path] = None,
) -> Optional[Path]:
    """Faz o download do PDF gerado, validando tamanho e content-type."""
    try:
        destino_base = Path(diretorio_saida) if diretorio_saida else Path(".")
        destino_base.mkdir(parents=True, exist_ok=True)
        destino_arquivo = destino_base / "processo.pdf"
        if processo:
            safe_numero = _sanitize_filename(processo.numero_processo.replace("/", "_").replace(".", "_"))
            destino_arquivo = destino_base / f"processo_{safe_numero}.pdf"

        headers = dict(DEFAULT_HEADERS)
        headers["Accept"] = "application/pdf, */*;q=0.8"
        log.info("Baixando arquivo: %s", url)

        response = session.get(url, timeout=120, headers=headers, allow_redirects=True, stream=True)
        response.raise_for_status()

        content_type = (response.headers.get("Content-Type") or "").lower()
        content_disp = response.headers.get("Content-Disposition") or ""

        if "application/pdf" in content_type or ".pdf" in content_disp.lower():
            tamanho_total = 0
            with open(destino_arquivo, "wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        handle.write(chunk)
                        tamanho_total += len(chunk)
                        if tamanho_total > 100 * 1024 * 1024:
                            raise SEIPDFError(f"Arquivo muito grande (>100MB): {tamanho_total} bytes")

            log.info("PDF salvo: %s (%.2f KB)", destino_arquivo, tamanho_total / 1024)
            if tamanho_total == 0:
                log.warning("Arquivo baixado está vazio")
                return None
            return destino_arquivo

        try:
            save_html(settings, settings.data_dir / "debug" / "processo_pdf_intermediario.html", response.text)
            log.warning("Download não retornou PDF. HTML salvo para inspeção.")
        except Exception:
            log.warning("Resposta do download não é texto nem PDF; verifique cabeçalhos/redirects.")
        return None

    except requests.Timeout:
        raise SEIPDFError("Timeout ao baixar PDF") from None
    except requests.RequestException as exc:
        raise SEIPDFError(f"Erro de rede ao baixar PDF: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, SEIPDFError):
            raise
        raise SEIPDFError(f"Erro inesperado ao baixar PDF: {exc}") from exc


def enviar_form_gerar(
    session: requests.Session,
    settings: Settings,
    html_form: str,
    referer_url: str,
    processo: Optional[Processo] = None,
    diretorio_saida: Optional[Path] = None,
) -> Path:
    """Submete o formulário de geração e acompanha redirecionamentos até obter o PDF."""
    try:
        soup = BeautifulSoup(html_form, "lxml")
        form: Optional[Tag] = None
        for candidate in soup.find_all("form"):
            if not isinstance(candidate, Tag):
                continue
            action = candidate.get("action", "")
            buttons = " ".join(inp.get("value", "") for inp in candidate.find_all("input", {"type": "submit"}) if isinstance(inp, Tag))
            if "procedimento_gerar_pdf" in action or "Gerar" in buttons:
                form = candidate
                break
        if not form:
            forms = soup.find_all("form")
            if not forms or not isinstance(forms[0], Tag):
                save_html(settings, settings.data_dir / "debug" / "processo_pdf_intermediario.html", html_form)
                raise SEIPDFError("Não encontrei formulário na página de opções")
            form = forms[0]

        action = form.get("action", "")
        method = form.get("method", "post").lower()
        url_action = absolute_to_sei(settings, action) if action else ""

        data = serializar_formulario(form)
        data["hdnFlagGerar"] = "1"
        data.setdefault("rdoTipo", "T")
        data.setdefault("btnGerar", "Gerar")

        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = referer_url
        headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"

        if method == "post":
            response = session.post(url_action, data=data, timeout=120, headers=headers, allow_redirects=True)
        else:
            response = session.get(url_action, params=data, timeout=120, headers=headers, allow_redirects=True)

        response.raise_for_status()
        response.encoding = "iso-8859-1"
        save_html(settings, settings.data_dir / "debug" / "processo_pdf_intermediario.html", response.text)

        url_download = extrair_url_download_do_html(settings, response.text)
        if not url_download and processo:
            import re

            match = re.search(r"document.getElementById\\('ifrDownload'\\)\\.src\\s*=\\s*['\"]([^'\"]+)['\"]", response.text, flags=re.I)
            if match:
                iframe_src = match.group(1)
                iframe_url = absolute_to_sei(settings, iframe_src)
                log.debug("Identifiquei iframe de download via JS; carregando %s", iframe_url)
                iframe_resp = session.get(iframe_url, timeout=60, headers=DEFAULT_HEADERS)
                iframe_resp.raise_for_status()
                iframe_resp.encoding = "iso-8859-1"
                save_html(settings, settings.data_dir / "debug" / "processo_pdf_iframe_download.html", iframe_resp.text)
                url_download = extrair_url_download_do_html(settings, iframe_resp.text)
                if not url_download:
                    mensagem = extrair_mensagem_erro_pdf(iframe_resp.text)
                    if mensagem:
                        raise SEIPDFError(f"SEI retornou erro ao gerar PDF: {mensagem}")

        if url_download:
            destino = baixar_por_url(session, settings, url_download, processo=processo, diretorio_saida=diretorio_saida)
            if not destino:
                raise SEIPDFError("Falha ao baixar PDF via URL do iframe")
            return destino

        mensagem = extrair_mensagem_erro_pdf(response.text)
        if mensagem:
            raise SEIPDFError(f"SEI retornou erro ao gerar PDF: {mensagem}")
        raise SEIPDFError("Não encontrei URL de download (acao=exibir_arquivo) na resposta")

    except requests.RequestException as exc:
        raise SEIPDFError(f"Erro de rede ao gerar PDF: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, SEIPDFError):
            raise
        raise SEIPDFError(f"Erro inesperado ao gerar PDF: {exc}") from exc


def gerar_pdf_processo(
    session: requests.Session,
    settings: Settings,
    processo: Processo,
    diretorio_saida: Optional[Path] = None,
) -> PDFDownloadResult:
    """Executa a geração do PDF para um único processo com apenas uma tentativa."""
    return baixar_pdf_processo(session, settings, processo, tentativas=1, diretorio_saida=diretorio_saida)


def baixar_pdf_processo(
    session: Optional[requests.Session],
    settings: Settings,
    processo: Processo,
    tentativas: int = 3,
    diretorio_saida: Optional[Path] = None,
    atraso_retry: float = 2.0,
) -> PDFDownloadResult:
    """Realiza todo o fluxo de abertura do processo, geração e download com retentativas."""
    inicio = time.time()
    destino: Optional[Path] = None
    erro: Optional[str] = None
    tentativas_realizadas = 0

    sessao_propria = False
    sessao = session
    if sessao is None:
        sessao = requests.Session()
        sessao.headers.update(DEFAULT_HEADERS)
        sessao_propria = True

    try:
        for tentativa in range(1, tentativas + 1):
            tentativas_realizadas = tentativa
            try:
                log.info("[PDF] (%s/%s) %s", tentativa, tentativas, processo.numero_processo)
                html_pai = abrir_processo(sessao, settings, processo)
                iframe_url = extrair_iframe_arvore_src(settings, html_pai)
                if not iframe_url:
                    raise SEIPDFError("Iframe 'ifrArvore' não encontrado.")

                html_iframe = carregar_iframe_arvore(sessao, settings, iframe_url)
                link_pdf = achar_link_gerar_pdf(settings, html_iframe)
                if not link_pdf:
                    raise SEIPDFError("Link 'procedimento_gerar_pdf' não encontrado.")

                html_form = abrir_pagina_gerar_pdf(sessao, settings, link_pdf)
                destino = enviar_form_gerar(
                    sessao,
                    settings,
                    html_form,
                    referer_url=link_pdf,
                    processo=processo,
                    diretorio_saida=diretorio_saida,
                )
                erro = None
                break
            except (SEIProcessoError, SEIPDFError) as exc:
                erro = str(exc)
                log.warning("[PDF] Falha %s/%s para %s: %s", tentativa, tentativas, processo.numero_processo, erro)
                if tentativa < tentativas:
                    time.sleep(min(atraso_retry * tentativa, 10))
                else:
                    break
            except Exception as exc:
                erro = str(exc)
                log.error("[PDF] Erro inesperado %s/%s para %s: %s", tentativa, tentativas, processo.numero_processo, erro)
                if tentativa < tentativas:
                    time.sleep(min(atraso_retry * tentativa, 10))
                else:
                    break

    finally:
        if sessao_propria and sessao:
            sessao.close()

    sucesso = destino is not None and erro is None
    return PDFDownloadResult(
        processo=processo,
        sucesso=sucesso,
        caminho=destino,
        erro=erro,
        tentativas=tentativas_realizadas,
        tempo_segundos=time.time() - inicio,
    )


def baixar_pdfs_em_lote(
    session: requests.Session,
    settings: Settings,
    processos: List[Processo],
    options: PDFDownloadOptions,
) -> List[PDFDownloadResult]:
    """Coordena o download de PDFs para vários processos, em série ou paralelo."""
    if not processos:
        log.warning("Nenhum processo disponível para download de PDF em lote.")
        return []

    processos_alvo = processos
    if options.limite_processos is not None and options.limite_processos > 0:
        processos_alvo = processos[: options.limite_processos]

    diretorio_saida = Path(options.diretorio_saida or ".").expanduser()
    diretorio_saida.mkdir(parents=True, exist_ok=True)

    log.info(
        "Iniciando download em lote de %s processo(s)%s.",
        len(processos_alvo),
        " (paralelo)" if options.paralelo else "",
    )

    resultados: List[PDFDownloadResult] = []
    inicio = time.time()

    if options.paralelo:
        log.warning("Atenção: execução paralela utiliza uma nova sessão por processo.")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max(1, options.workers)) as executor:
            futuros = {
                executor.submit(
                    baixar_pdf_processo,
                    None,
                    settings,
                    processo,
                    options.tentativas,
                    diretorio_saida,
                ): processo
                for processo in processos_alvo
            }
            for futuro in as_completed(futuros):
                resultados.append(futuro.result())
    else:
        for idx, processo in enumerate(processos_alvo, start=1):
            log.info("[PDF] Processo %s/%s: %s", idx, len(processos_alvo), processo.numero_processo)
            resultado = baixar_pdf_processo(
                session,
                settings,
                processo,
                tentativas=options.tentativas,
                diretorio_saida=diretorio_saida,
            )
            resultados.append(resultado)
            if idx < len(processos_alvo):
                time.sleep(1)

    sucessos = [r for r in resultados if r.sucesso]
    falhas = [r for r in resultados if not r.sucesso]
    tempo_total = time.time() - inicio

    log.info(
        "Download em lote finalizado: %s sucesso(s), %s falha(s). Tempo total: %.1fs",
        len(sucessos),
        len(falhas),
        tempo_total,
    )

    if falhas:
        log.warning("Falhas ao gerar PDF em %s processo(s):", len(falhas))
        for falha in falhas[:5]:
            log.warning("  - %s (%s)", falha.processo.numero_processo, falha.erro or "motivo desconhecido")

    return resultados

