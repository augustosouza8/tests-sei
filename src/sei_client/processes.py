"""Rotinas para coletar, paginar e aplicar filtros a processos dentro do SEI."""

from __future__ import annotations

import logging
import math
import re
from typing import Dict, Iterable, List, Literal, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup, Tag

from .config import Settings
from .exceptions import SEIProcessoError
from .http import DEFAULT_HEADERS, absolute_to_sei, save_html
from .models import FilterOptions, PaginationInfo, PaginationOptions, Processo
from .dom import serializar_formulario

log = logging.getLogger(__name__)

RE_PROCESSO = re.compile(r"\b\d{4}\.\s?\d{2}\.\s?\d{7}\s*/\s*\d{4}\s*[-–—-]\s*\d{2}\b", re.I)
RE_TOOLTIP = re.compile(r"infraTooltipMostrar\('([^']*)',\s*'([^']*)'\)", re.I)


def _get_attr_str(tag: Optional[Tag], attr: str, default: str = "") -> str:
    """Obtém atributo de uma tag garantindo retorno textual."""
    if not tag:
        return default
    value = tag.get(attr, default)
    if isinstance(value, list):
        return value[0] if value else default
    return str(value) if value else default


def canonizar_processo(txt: str) -> str:
    """Normaliza a representação textual dos números de processo."""
    txt = txt.replace("\xa0", " ")
    txt = re.sub(r"\.\s+", ".", txt)
    txt = re.sub(r"\s*/\s*", "/", txt)
    txt = re.sub(r"\s*-\s*", "-", txt)
    return txt.strip()


def extrair_id_procedimento_da_url(url: str) -> str:
    """Retorna o `id_procedimento` presente na URL do processo."""
    try:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get("id_procedimento", [""])[0]
    except Exception:
        return ""


def extrair_hash_da_url(url: str) -> str:
    """Extrai o hash usado pelo SEI para validar o acesso ao processo."""
    try:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get("infra_hash", [""])[0]
    except Exception:
        return ""


def parse_tooltip(onmouseover: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Decodifica títulos e tipos exibidos nos tooltips do SEI."""
    if not onmouseover:
        return None, None
    match = RE_TOOLTIP.search(onmouseover)
    if match:
        titulo = match.group(1).strip() if match.group(1) else None
        tipo = match.group(2).strip() if match.group(2) else None
        return titulo, tipo
    return None, None


def extrair_processo_da_linha(
    settings: Settings,
    linha: Tag,
    categoria: Literal["Recebidos", "Gerados"],
) -> Optional[Processo]:
    """Transforma uma linha da tabela HTML em instância `Processo`."""
    try:
        link_processo = linha.select_one('a[href*="acao=procedimento_trabalhar"]')
        if not link_processo or not isinstance(link_processo, Tag):
            return None

        txt = link_processo.get_text(" ", strip=True)
        title_attr = _get_attr_str(link_processo, "title")
        href_attr = _get_attr_str(link_processo, "href")
        match = RE_PROCESSO.search(txt) or RE_PROCESSO.search(title_attr) or RE_PROCESSO.search(href_attr)
        if not match:
            return None

        numero_processo = canonizar_processo(match.group(0))
        href = href_attr
        if not href:
            return None

        url = absolute_to_sei(settings, href)

        classes = link_processo.get("class", [])
        if isinstance(classes, str):
            classes = [classes]
        visualizado = "processoVisualizado" in classes

        id_procedimento = extrair_id_procedimento_da_url(url)
        hash_proc = extrair_hash_da_url(url)

        onmouseover = _get_attr_str(link_processo, "onmouseover")
        titulo, tipo_especificidade = parse_tooltip(onmouseover if onmouseover else None)

        responsavel_nome = None
        responsavel_cpf = None
        link_responsavel = linha.select_one('a[href*="acao=procedimento_atribuicao_listar"]')
        if link_responsavel and isinstance(link_responsavel, Tag):
            title_resp = _get_attr_str(link_responsavel, "title")
            responsavel_nome = title_resp.replace("Atribuído para ", "") if title_resp else None
            responsavel_cpf = link_responsavel.get_text(strip=True)

        marcadores: List[str] = []
        for img in linha.select("img.imagemStatus"):
            if not isinstance(img, Tag):
                continue
            parent_link = img.find_parent("a")
            if parent_link and isinstance(parent_link, Tag):
                onmouseover_attr = _get_attr_str(parent_link, "onmouseover")
                if onmouseover_attr:
                    tooltip_match = re.search(r"infraTooltipMostrar\('([^']*)'", onmouseover_attr)
                    if tooltip_match:
                        marcadores.append(tooltip_match.group(1).strip())

        tem_documentos_novos = bool(linha.select_one('img[src*="exclamacao.svg"]'))
        tem_anotacoes = bool(linha.select_one('img[src*="anotacao"]'))

        return Processo(
            numero_processo=numero_processo,
            id_procedimento=id_procedimento,
            url=url,
            visualizado=visualizado,
            categoria=categoria,
            titulo=titulo,
            tipo_especificidade=tipo_especificidade,
            responsavel_nome=responsavel_nome,
            responsavel_cpf=responsavel_cpf,
            marcadores=marcadores,
            tem_documentos_novos=tem_documentos_novos,
            tem_anotacoes=tem_anotacoes,
            hash=hash_proc,
        )
    except Exception as exc:
        log.debug("Erro ao extrair processo da linha: %s", exc)
        return None


def extrair_processos(settings: Settings, html_controle: str) -> List[Processo]:
    """Percorre a página do controle e devolve a lista inicial de processos."""
    try:
        soup = BeautifulSoup(html_controle, "lxml")
        processos: List[Processo] = []
        processos_ids: Set[str] = set()

        tabela_recebidos = soup.select_one("#tblProcessosRecebidos")
        if tabela_recebidos:
            linhas = tabela_recebidos.select("tr[id^='P']")
            for linha in linhas:
                proc = extrair_processo_da_linha(settings, linha, "Recebidos")
                if proc and proc.id_procedimento and proc.id_procedimento not in processos_ids:
                    processos.append(proc)
                    processos_ids.add(proc.id_procedimento)

        tabela_gerados = soup.select_one("#tblProcessosGerados")
        if tabela_gerados:
            linhas = tabela_gerados.select("tr[id^='P']")
            for linha in linhas:
                proc = extrair_processo_da_linha(settings, linha, "Gerados")
                if proc and proc.id_procedimento and proc.id_procedimento not in processos_ids:
                    processos.append(proc)
                    processos_ids.add(proc.id_procedimento)

        log.info(
            "Total de processos extraídos: %s (%s Recebidos, %s Gerados)",
            len(processos),
            sum(1 for p in processos if p.categoria == "Recebidos"),
            sum(1 for p in processos if p.categoria == "Gerados"),
        )
        return processos

    except Exception as exc:
        raise SEIProcessoError(f"Erro ao extrair processos: {exc}") from exc


def _parse_caption_info(texto: str) -> tuple[int, int]:
    """Extrai total de registros e itens por página a partir da legenda da tabela."""
    total_registros = 0
    itens_por_pagina = 0

    m_total = re.search(r"(\d+)\s+registros", texto)
    if m_total:
        total_registros = int(m_total.group(1))

    m_intervalo = re.search(r"-\s*(\d+)\s*a\s*(\d+)", texto)
    if m_intervalo:
        inicio = int(m_intervalo.group(1))
        fim = int(m_intervalo.group(2))
        itens_por_pagina = max(0, fim - inicio + 1)

    if itens_por_pagina == 0 and total_registros:
        itens_por_pagina = total_registros

    return total_registros, itens_por_pagina


def obter_paginacao_info(html_controle: str) -> Dict[str, PaginationInfo]:
    """Lê metadados de paginação das tabelas de processos."""
    soup = BeautifulSoup(html_controle, "lxml")
    info: Dict[str, PaginationInfo] = {}

    for grupo in ("Recebidos", "Gerados"):
        tabela = soup.select_one(f"#tblProcessos{grupo}")
        total_registros = 0
        itens_por_pagina = 0

        if tabela:
            caption = tabela.find("caption")
            if caption:
                total_registros, itens_por_pagina = _parse_caption_info(caption.get_text(" ", strip=True))
            linhas = tabela.select("tr[id^='P']")
            if itens_por_pagina <= 0 and linhas:
                itens_por_pagina = len(linhas)
            if total_registros <= 0 and linhas:
                total_registros = len(linhas)

        hidden_nro = soup.select_one(f"#hdn{grupo}NroItens")
        valor_nro = _get_attr_str(hidden_nro, "value") if hidden_nro else None
        if valor_nro:
            try:
                nro_itens = int(valor_nro)
                if itens_por_pagina <= 0:
                    itens_por_pagina = nro_itens
            except ValueError:
                pass

        hidden_itens = soup.select_one(f"#hdn{grupo}Itens")
        valor_itens = _get_attr_str(hidden_itens, "value") if hidden_itens else None
        if total_registros <= 0 and valor_itens:
            total_registros = len([item for item in valor_itens.split(",") if item])

        hidden_pagina = soup.select_one(f"#hdn{grupo}PaginaAtual")
        valor_pagina = _get_attr_str(hidden_pagina, "value") if hidden_pagina else None
        pagina_atual = 0
        if valor_pagina:
            try:
                pagina_atual = int(valor_pagina)
            except ValueError:
                pagina_atual = 0

        if itens_por_pagina <= 0:
            itens_por_pagina = max(1, total_registros if total_registros else 1)

        total_paginas = max(1, math.ceil(total_registros / itens_por_pagina)) if itens_por_pagina else 1
        info[grupo] = PaginationInfo(
            total_registros=total_registros,
            pagina_atual=pagina_atual,
            total_paginas=total_paginas,
            itens_por_pagina=itens_por_pagina,
        )

    return info


def submeter_paginacao(
    session: requests.Session,
    settings: Settings,
    html_atual: str,
    grupo: Literal["Recebidos", "Gerados"],
    pagina_destino: int,
    controle_url: str,
) -> str:
    """Envia o formulário de controle solicitando uma nova página de resultados."""
    soup = BeautifulSoup(html_atual, "lxml")
    form = soup.select_one("#frmProcedimentoControlar")
    if not form:
        raise SEIProcessoError("Formulário de controle não encontrado para paginação.")

    data = serializar_formulario(form)
    alvo = str(pagina_destino)

    select_superior = f"sel{grupo}PaginacaoSuperior"
    select_inferior = f"sel{grupo}PaginacaoInferior"
    hidden_pagina = f"hdn{grupo}PaginaAtual"

    if select_superior in data:
        data[select_superior] = alvo
    if select_inferior in data:
        data[select_inferior] = alvo
    if hidden_pagina in data:
        data[hidden_pagina] = alvo
    else:
        raise SEIProcessoError(f"Paginação indisponível para {grupo}.")

    action = _get_attr_str(form, "action")
    url_action = absolute_to_sei(settings, action)
    headers = dict(DEFAULT_HEADERS)
    headers.setdefault("Referer", controle_url)

    resposta = session.post(url_action, data=data, headers=headers, timeout=60)
    resposta.raise_for_status()
    resposta.encoding = "iso-8859-1"

    save_html(settings, settings.data_dir / "debug" / f"controle_{grupo.lower()}_{pagina_destino + 1}.html", resposta.text)

    return resposta.text


def _adicionar_processos(destino: List[Processo], novos: Iterable[Processo]) -> None:
    """Anexa processos inéditos à lista destino preservando ordem de chegada."""
    vistos: Set[str] = {proc.id_procedimento or proc.numero_processo for proc in destino}
    for processo in novos:
        chave = processo.id_procedimento or processo.numero_processo
        if chave and chave not in vistos:
            destino.append(processo)
            vistos.add(chave)


def coletar_processos_com_paginacao(
    session: requests.Session,
    settings: Settings,
    html_inicial: str,
    controle_url: str,
    paginacao: PaginationOptions,
) -> List[Processo]:
    """Percorre as páginas do controle acumulando todos os processos possíveis."""
    processos: List[Processo] = []

    info_inicial = obter_paginacao_info(html_inicial)
    _adicionar_processos(processos, extrair_processos(settings, html_inicial))

    info_recebidos = info_inicial.get("Recebidos")
    if info_recebidos:
        limite_receb = paginacao.limite_para("Recebidos", info_recebidos.total_paginas)
        html_receb = html_inicial
        for pagina in range(info_recebidos.pagina_atual + 1, limite_receb):
            log.info("Carregando página %s/%s de Recebidos", pagina + 1, info_recebidos.total_paginas)
            html_receb = submeter_paginacao(session, settings, html_receb, "Recebidos", pagina, controle_url)
            _adicionar_processos(processos, extrair_processos(settings, html_receb))

    info_gerados = info_inicial.get("Gerados")
    if info_gerados:
        limite_ger = paginacao.limite_para("Gerados", info_gerados.total_paginas)
        html_ger = html_inicial
        for pagina in range(info_gerados.pagina_atual + 1, limite_ger):
            log.info("Carregando página %s/%s de Gerados", pagina + 1, info_gerados.total_paginas)
            html_ger = submeter_paginacao(session, settings, html_ger, "Gerados", pagina, controle_url)
            _adicionar_processos(processos, extrair_processos(settings, html_ger))

    return processos


def aplicar_filtros(processos: List[Processo], filtros: FilterOptions) -> List[Processo]:
    """Aplica filtros em memória sobre a lista de processos coletada."""
    if not processos:
        return []

    resultado = processos

    if filtros.categorias:
        resultado = [p for p in resultado if p.categoria in filtros.categorias]

    if filtros.visualizacao == "visualizados":
        resultado = [p for p in resultado if p.visualizado]
    elif filtros.visualizacao == "nao_visualizados":
        resultado = [p for p in resultado if not p.visualizado]

    if filtros.com_documentos_novos is True:
        resultado = [p for p in resultado if p.tem_documentos_novos]
    elif filtros.com_documentos_novos is False:
        resultado = [p for p in resultado if not p.tem_documentos_novos]

    if filtros.com_anotacoes is True:
        resultado = [p for p in resultado if p.tem_anotacoes]
    elif filtros.com_anotacoes is False:
        resultado = [p for p in resultado if not p.tem_anotacoes]

    def _matches_any(target: Optional[str], termos: Iterable[str]) -> bool:
        termos_list = list(termos)
        if not termos_list:
            return True
        alvo = (target or "").casefold()
        return any(termo.casefold() in alvo for termo in termos_list)

    if filtros.responsaveis:
        resultado = [p for p in resultado if _matches_any(p.responsavel_nome, filtros.responsaveis)]

    if filtros.tipos:
        resultado = [p for p in resultado if _matches_any(p.tipo_especificidade, filtros.tipos)]

    if filtros.marcadores:
        termos = [m.casefold() for m in filtros.marcadores]
        resultado = [
            p
            for p in resultado
            if any(any(termo in marcador.casefold() for termo in termos) for marcador in p.marcadores)
        ]

    return resultado


def coletar_processos(
    session: requests.Session,
    settings: Settings,
    filtros: FilterOptions,
    paginacao: PaginationOptions,
    html_controle_inicial: str,
    controle_url: str,
) -> tuple[List[Processo], List[Processo]]:
    """Combina coleta com paginação e aplicação de filtros retornando listas úteis."""
    processos = coletar_processos_com_paginacao(session, settings, html_controle_inicial, controle_url, paginacao)
    total_processos = len(processos)

    if not processos:
        log.warning("Nenhum processo encontrado")
        return processos, []

    processos_filtrados = aplicar_filtros(processos, filtros)

    if filtros.limite is not None:
        if filtros.limite < 1:
            log.warning("Limite deve ser >= 1; ignorando valor informado.")
        else:
            processos_filtrados = processos_filtrados[: filtros.limite]
            log.info("Aplicado limite de %s processo(s).", filtros.limite)

    if len(processos_filtrados) != total_processos:
        log.info("Total de processos após filtros: %s", len(processos_filtrados))

    if not processos_filtrados:
        log.warning("Nenhum processo após aplicar os filtros.")

    return processos, processos_filtrados


def abrir_processo(session: requests.Session, settings: Settings, processo: Processo) -> str:
    """Abre a página detalhada de um processo específico."""
    try:
        log.info("Abrindo processo: %s", processo.numero_processo)
        response = session.get(processo.url, timeout=30, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        response.encoding = "iso-8859-1"
        safe_name = processo.numero_processo.replace("/", "_").replace(".", "_")
        save_html(settings, settings.data_dir / "debug" / f"processo_{safe_name}.html", response.text)
        return response.text
    except requests.RequestException as exc:
        raise SEIProcessoError(f"Erro ao acessar processo {processo.numero_processo}: {exc}") from exc

