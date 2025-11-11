"""Funções responsáveis por enriquecer processos com documentos e metadados associados."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup, Tag

from .config import Settings
from .exceptions import SEIPDFError, SEIProcessoError
from .http import DEFAULT_HEADERS, absolute_to_sei, save_html
from .models import Documento, EnrichmentOptions, Processo
from .processes import extrair_hash_da_url

log = logging.getLogger(__name__)

RE_INFRA_NO = re.compile(r"Nos\[(?P<index>\d+)\]\s*=\s*new\s+infraArvoreNo\((?P<args>.*?)\);", re.S)
RE_NO_ASSIGNMENT = re.compile(
    r"Nos\[(?P<index>\d+)\]\.(?P<prop>\w+)\s*=\s*(?P<value>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\"|[^;]+);",
    re.S,
)
RE_INFRA_ACAO = re.compile(r"NosAcoes\[(?P<index>\d+)\]\s*=\s*new\s+infraArvoreAcao\((?P<args>.*?)\);", re.S)


def _convert_js_literal(value: str) -> Any:
    """Transforma valores literais presentes no JavaScript do SEI para equivalentes Python."""
    cleaned = value.strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r"\.concat\(['\"]{0,1}['\"]{0,1}\)", "", cleaned)

    replacements = {"null": "None", "true": "True", "false": "False"}

    def _replace_boolean(match: re.Match[str]) -> str:
        return replacements.get(match.group(0), match.group(0))

    cleaned = re.sub(r"\b(null|true|false)\b", _replace_boolean, cleaned)

    import ast

    try:
        return ast.literal_eval(cleaned)
    except (ValueError, SyntaxError):
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
            return cleaned[1:-1]
        return cleaned


def _parse_infra_args(args_str: str) -> List[Any]:
    """Quebra a lista de argumentos usada na árvore JS em elementos Python típicos."""
    texto = args_str.strip()
    if not texto:
        return []

    texto = re.sub(r"\b(null|true|false)\b", lambda m: {"null": "None", "true": "True", "false": "False"}[m.group(0)], texto)

    import ast

    try:
        parsed = ast.literal_eval(f"[{texto}]")
        if isinstance(parsed, (list, tuple)):
            return list(parsed)
        return [parsed]
    except (ValueError, SyntaxError):
        log.debug("Falha ao interpretar argumentos do infraArvoreNo; retornando lista vazia.")
        return []


def _as_optional_str(value: Any) -> Optional[str]:
    """Converte o valor recebido em string, preservando `None` quando apropriado."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _extract_first_href(html_fragment: str) -> Optional[str]:
    """Procura o primeiro link válido dentro de um fragmento HTML."""
    if not html_fragment:
        return None
    try:
        frag = BeautifulSoup(html_fragment, "lxml")
        link = frag.find("a", href=True)
        if isinstance(link, Tag):
            href = link.get("href")
            return href if isinstance(href, str) else None
    except Exception:
        log.debug("Não foi possível extrair href do fragmento HTML.", exc_info=log.isEnabledFor(logging.DEBUG))
    return None


def _append_unique(target: List[str], value: str) -> None:
    """Adiciona `value` à lista apenas se ele ainda não estiver presente."""
    if value and value not in target:
        target.append(value)


def _extract_alert_text(js_code: Optional[str]) -> Optional[str]:
    """Extrai o texto exibido em `alert(...)` a partir de trechos JavaScript."""
    if not js_code:
        return None
    match = re.search(r"alert\((['\"])(?P<content>.*?)\1\)", js_code, flags=re.S)
    if not match:
        return None
    content = match.group("content")
    content = (
        content.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace("\\'", "'")
        .replace('\\"', '"')
    )
    return content


def _extract_assinatura_nomes(alert_text: Optional[str]) -> List[str]:
    """Constrói a lista de nomes de assinantes a partir do texto exibido pelo SEI."""
    if not alert_text:
        return []

    texto = alert_text.strip()
    if not texto:
        return []

    grupos = [grupo for grupo in re.split(r"\n\s*\n", texto) if grupo.strip()]
    nomes: List[str] = []
    for grupo in grupos:
        linhas = [linha.strip() for linha in grupo.splitlines() if linha.strip()]
        if not linhas:
            continue

        if linhas[0].lower().startswith("assinado por"):
            linhas = linhas[1:]
        if not linhas:
            continue

        nome = linhas[0]
        if nome:
            _append_unique(nomes, nome)

    if not nomes and texto.lower().startswith("assinado por"):
        linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
        if len(linhas) > 1:
            _append_unique(nomes, linhas[1])

    return nomes


def extrair_iframe_arvore_src(settings: Settings, html_pai: str) -> Optional[str]:
    """Localiza a URL do iframe com a árvore de documentos dentro da página do processo."""
    try:
        soup = BeautifulSoup(html_pai, "lxml")
        iframe = soup.select_one("#ifrArvore")
        if not iframe or not isinstance(iframe, Tag):
            return None
        src = iframe.get("src")
        if not isinstance(src, str):
            return None
        return absolute_to_sei(settings, src)
    except Exception as exc:
        log.warning("Erro ao extrair iframe arvore: %s", exc)
        return None


def carregar_iframe_arvore(session: requests.Session, settings: Settings, iframe_url: str) -> str:
    """Baixa o conteúdo HTML do iframe de documentos para posterior parsing."""
    try:
        log.info("Carregando iframe (ifrArvore): %s", iframe_url)
        response = session.get(iframe_url, timeout=30, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        response.encoding = "iso-8859-1"
        save_html(settings, settings.data_dir / "debug" / "processo_iframe.html", response.text)
        return response.text
    except requests.RequestException as exc:
        raise SEIPDFError(f"Erro ao carregar iframe: {exc}") from exc


def parse_documentos_do_iframe(
    settings: Settings,
    html_iframe: str,
    processo: Optional[Processo] = None,
) -> List[Documento]:
    """Analisa o HTML do iframe e retorna a lista de documentos estruturados."""
    if not html_iframe:
        return []

    soup = BeautifulSoup(html_iframe, "lxml")
    scripts = soup.find_all("script")
    if not scripts:
        return []

    script_text = "\n".join((script.string or script.get_text() or "") for script in scripts)
    if not script_text.strip():
        return []

    documentos_por_indice: Dict[int, Documento] = {}

    for match in RE_INFRA_NO.finditer(script_text):
        idx = int(match.group("index"))
        args_raw = match.group("args")
        args = _parse_infra_args(args_raw)
        if len(args) < 7:
            continue

        tipo_no = _as_optional_str(args[0])
        if not tipo_no or "DOCUMENTO" not in tipo_no.upper():
            continue

        id_documento = _as_optional_str(args[1]) or ""
        parent_id = _as_optional_str(args[2]) if len(args) > 2 else None
        href = _as_optional_str(args[3])
        iframe_target = _as_optional_str(args[4])
        aux = _as_optional_str(args[5])
        label = _as_optional_str(args[6]) or aux or id_documento
        icon_path = _as_optional_str(args[7]) if len(args) > 7 else None
        classe_css = _as_optional_str(args[14]) if len(args) > 14 else None
        numero_documento = _as_optional_str(args[15]) if len(args) > 15 else None

        doc = Documento(
            id_documento=id_documento,
            titulo=label,
            tipo=tipo_no,
            url=absolute_to_sei(settings, href) if href else None,
            hash=None,
        )
        if href:
            doc.hash = extrair_hash_da_url(href)

        if numero_documento:
            doc.metadados["numero_documento"] = numero_documento
        if parent_id:
            doc.metadados["id_parent"] = parent_id
        if iframe_target:
            doc.metadados["iframe_target"] = iframe_target
        if tipo_no:
            doc.metadados["tipo_no"] = tipo_no
        if icon_path:
            doc.metadados["icone"] = icon_path
            icon_slug = icon_path.split("/")[-1].split("?")[0]
            doc.metadados["icone_slug"] = icon_slug
            if "sigilo" in icon_path.lower():
                doc.eh_sigiloso = True
        if classe_css:
            doc.indicadores.append(classe_css)
            if "novisitado" in classe_css.lower():
                doc.eh_novo = True
            doc.metadados["classe_css"] = classe_css

        doc.metadados["ordem"] = idx
        documentos_por_indice[idx] = doc

    if not documentos_por_indice:
        return []

    documentos_por_id: Dict[str, Documento] = {
        documento.id_documento: documento for documento in documentos_por_indice.values() if documento.id_documento
    }

    processo_assinantes: List[str] = []

    for match in RE_NO_ASSIGNMENT.finditer(script_text):
        idx = int(match.group("index"))
        prop = match.group("prop")
        if prop not in {"assinatura", "src", "html"}:
            continue

        doc = documentos_por_indice.get(idx)
        if not doc:
            continue

        raw_value = match.group("value")
        parsed_value = _convert_js_literal(raw_value)

        if prop == "assinatura":
            if isinstance(parsed_value, str) and parsed_value.strip():
                assinatura_text = BeautifulSoup(parsed_value, "lxml").get_text(" ", strip=True)
                if assinatura_text:
                    doc.possui_assinaturas = True
                    doc.assinantes = [assinatura_text]
                    doc.metadados["assinatura_texto"] = assinatura_text
        elif prop == "src":
            if isinstance(parsed_value, str) and parsed_value:
                url_rel = parsed_value
                url_abs = absolute_to_sei(settings, url_rel)
                lower_rel = url_rel.lower()
                if "documento_visualizar" in lower_rel:
                    doc.visualizacao_url = url_abs
                elif "documento_download_anexo" in lower_rel or "acao=documento_download_anexo" in lower_rel:
                    doc.download_url = url_abs
                else:
                    doc.download_url = url_abs
                doc.metadados.setdefault("src_original", url_rel)
        elif prop == "html":
            if isinstance(parsed_value, str) and parsed_value:
                doc.metadados["html_fragmento"] = parsed_value
                href_visualizacao = _extract_first_href(parsed_value)
                if href_visualizacao:
                    doc.visualizacao_url = absolute_to_sei(settings, href_visualizacao)

    from .processes import extrair_hash_da_url  # import tardio para evitar ciclo

    for match in RE_INFRA_ACAO.finditer(script_text):
        args_raw = match.group("args")
        args = _parse_infra_args(args_raw)
        if not args:
            continue

        tipo_acao = (_as_optional_str(args[0]) or "").upper()
        alvo_id = _as_optional_str(args[2]) if len(args) > 2 else None
        js_code = _as_optional_str(args[3]) if len(args) > 3 else None
        label = _as_optional_str(args[5]) if len(args) > 5 else None
        icon = _as_optional_str(args[6]) if len(args) > 6 else None

        alvo_doc = documentos_por_id.get(alvo_id or "")

        if tipo_acao == "ASSINATURA":
            alerta = _extract_alert_text(js_code) or (label or "")
            nomes = _extract_assinatura_nomes(alerta)
            if alvo_doc:
                if alerta:
                    alvo_doc.metadados.setdefault("assinatura_alerta", alerta)
                if nomes:
                    alvo_doc.possui_assinaturas = True
                    for nome in nomes:
                        _append_unique(alvo_doc.assinantes, nome)
            elif processo and alvo_id and alvo_id == processo.id_procedimento:
                if alerta:
                    processo.metadados.setdefault("assinatura_alertas", []).append(alerta)
                for nome in nomes:
                    _append_unique(processo_assinantes, nome)
            continue

        if tipo_acao == "NIVEL_ACESSO":
            alerta = _extract_alert_text(js_code) or (label or "")
            if alvo_doc:
                alvo_doc.eh_sigiloso = True
                if icon:
                    alvo_doc.metadados.setdefault("acoes_icones", []).append(icon)
                if alerta:
                    alvo_doc.metadados.setdefault("nivel_acesso", alerta)
            elif processo and alvo_id and alvo_id == processo.id_procedimento:
                processo.eh_sigiloso = True
                if alerta:
                    processo.metadados.setdefault("nivel_acesso", alerta)
            continue

        if alvo_doc and icon:
            alvo_doc.metadados.setdefault("acoes_icones", []).append(icon)

    if processo and processo_assinantes:
        processo.assinantes = processo_assinantes

    documentos_ordenados = [documentos_por_indice[idx] for idx in sorted(documentos_por_indice.keys())]
    log.debug(
        "Extraídos %s documento(s) do processo %s.",
        len(documentos_ordenados),
        processo.numero_processo if processo else "desconhecido",
    )
    return documentos_ordenados


def enriquecer_processos(
    session: requests.Session,
    settings: Settings,
    processos: List[Processo],
    options: EnrichmentOptions,
    abrir_processo_fn: Callable[[requests.Session, Settings, Processo], str],
) -> List[Processo]:
    """Completa os dados dos processos com documentos, assinaturas e dumps opcionais."""
    if not options.coletar_documentos or not processos:
        return processos

    limite = options.limite_documentos
    if limite is not None and limite < 1:
        log.warning("Limite inferior a 1 informado para coleta de documentos; ignorando.")
        limite = None

    processos_alvo = processos if limite is None else processos[:limite]

    log.info("Coletando documentos para %s processo(s).", len(processos_alvo))

    for idx, processo in enumerate(processos_alvo, start=1):
        try:
            html_pai = abrir_processo_fn(session, settings, processo)
        except SEIProcessoError as exc:
            log.error("Falha ao abrir processo %s: %s", processo.numero_processo, exc)
            processo.documentos = []
            continue

        processo.assinantes = []
        processo.eh_sigiloso = False
        processo.metadados.clear()

        iframe_url = extrair_iframe_arvore_src(settings, html_pai)
        if not iframe_url:
            log.warning("Processo %s sem iframe de árvore identificado.", processo.numero_processo)
            processo.documentos = []
            continue

        try:
            html_iframe = carregar_iframe_arvore(session, settings, iframe_url)
        except SEIPDFError as exc:
            log.error("Falha ao carregar iframe do processo %s: %s", processo.numero_processo, exc)
            processo.documentos = []
            continue

        documentos = parse_documentos_do_iframe(settings, html_iframe, processo=processo)
        processo.documentos = documentos

        if options.dump_iframes and options.dump_iframes_dir:
            if options.dump_iframes_limite is not None and idx > options.dump_iframes_limite:
                continue
            options.dump_iframes_dir.mkdir(parents=True, exist_ok=True)
            safe_name = processo.numero_processo.replace("/", "_").replace(".", "_")
            arquivo = options.dump_iframes_dir / f"{idx:03d}_{safe_name}.html"
            try:
                arquivo.write_text(html_iframe, encoding="iso-8859-1")
                log.info("Iframe do processo %s salvo em %s", processo.numero_processo, arquivo)
            except Exception as exc:
                log.error("Falha ao salvar iframe do processo %s: %s", processo.numero_processo, exc)

    if limite is not None and len(processos) > limite:
        for processo in processos[limite:]:
            processo.documentos = []

    return processos

