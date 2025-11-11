"""Funções utilitárias para interpretar parâmetros de linha de comando e ambiente."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional, Set

from .config import Settings, _str_to_bool
from .models import EnrichmentOptions, FilterOptions, PDFDownloadOptions, PaginationOptions


def parse_cli_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Constrói o parser e interpreta os argumentos CLI disponíveis."""
    parser = argparse.ArgumentParser(
        description="Acessa o SEI, lista processos e gera PDF do primeiro processo filtrado.",
    )

    vis_group = parser.add_mutually_exclusive_group()
    vis_group.add_argument(
        "--filtro-visualizados",
        dest="filtro_visualizados",
        action="store_const",
        const="visualizados",
        default=None,
        help="Filtra apenas processos visualizados.",
    )
    vis_group.add_argument(
        "--filtro-nao-visualizados",
        dest="filtro_nao_visualizados",
        action="store_const",
        const="nao_visualizados",
        default=None,
        help="Filtra apenas processos não visualizados.",
    )

    parser.add_argument(
        "--categoria",
        action="append",
        choices=["recebidos", "gerados"],
        dest="categorias",
        help="Restringe a categoria dos processos (pode ser usada múltiplas vezes).",
    )
    parser.add_argument(
        "--responsavel",
        action="append",
        dest="responsaveis",
        help="Filtra por responsável (substring, pode ser usada múltiplas vezes).",
    )
    parser.add_argument(
        "--tipo",
        action="append",
        dest="tipos",
        help="Filtra por tipo/especificidade (substring, pode ser usada múltiplas vezes).",
    )
    parser.add_argument(
        "--marcador",
        action="append",
        dest="marcadores",
        help="Filtra por marcador/status (substring, pode ser usada múltiplas vezes).",
    )
    parser.add_argument(
        "--com-documentos-novos",
        dest="com_documentos_novos",
        action="store_true",
        default=None,
        help="Filtra processos com documentos novos.",
    )
    parser.add_argument(
        "--com-anotacoes",
        dest="com_anotacoes",
        action="store_true",
        default=None,
        help="Filtra processos com anotações.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        dest="limite",
        help="Limita a quantidade de processos após aplicar os filtros.",
    )
    parser.add_argument(
        "--exportar-xlsx",
        dest="exportar_xlsx",
        metavar="CAMINHO",
        help="Exporta os processos filtrados para um arquivo .xlsx no caminho informado.",
    )
    parser.add_argument(
        "--paginas-recebidos",
        type=int,
        dest="paginas_recebidos",
        help="Limita a quantidade de páginas processadas da lista de Recebidos.",
    )
    parser.add_argument(
        "--paginas-gerados",
        type=int,
        dest="paginas_gerados",
        help="Limita a quantidade de páginas processadas da lista de Gerados.",
    )
    parser.add_argument(
        "--paginas-max",
        type=int,
        dest="paginas_max",
        help="Limita o número de páginas para qualquer categoria (aplica-se a todas).",
    )
    parser.add_argument(
        "--coletar-documentos",
        dest="coletar_documentos",
        action="store_true",
        default=False,
        help="Coleta metadados dos documentos de cada processo.",
    )
    parser.add_argument(
        "--limite-processos-documentos",
        type=int,
        dest="limite_processos_documentos",
        help="Limita a quantidade de processos ao coletar documentos/iframes.",
    )
    parser.add_argument(
        "--dump-iframes",
        dest="dump_iframes",
        action="store_true",
        default=False,
        help="Salva HTML dos iframes dos processos selecionados em disco.",
    )
    parser.add_argument(
        "--dump-iframes-limite",
        type=int,
        dest="dump_iframes_limite",
        help="Limita o número de iframes salvos (default: 5).",
    )
    parser.add_argument(
        "--dump-iframes-dir",
        dest="dump_iframes_dir",
        help="Diretório onde os iframes serão salvos (default: data/iframes).",
    )
    parser.add_argument(
        "--salvar-historico",
        dest="salvar_historico",
        action="store_true",
        default=False,
        help="Salva histórico dos processos coletados em JSON.",
    )
    parser.add_argument(
        "--historico-arquivo",
        dest="historico_arquivo",
        help="Arquivo JSON para salvar o histórico (default: data/historico_processos.json).",
    )
    parser.add_argument(
        "--download-lote",
        dest="download_lote",
        action="store_true",
        default=False,
        help="Baixa PDFs de múltiplos processos filtrados.",
    )
    parser.add_argument(
        "--max-processos-pdf",
        type=int,
        dest="max_processos_pdf",
        help="Limite de processos a processar no download em lote.",
    )
    parser.add_argument(
        "--pdf-dir",
        dest="pdf_dir",
        help="Diretório para salvar os PDFs gerados (default: ./).",
    )
    parser.add_argument(
        "--pdf-paralelo",
        dest="pdf_paralelo",
        action="store_true",
        default=False,
        help="Processa downloads em paralelo (usa threads).",
    )
    parser.add_argument(
        "--pdf-workers",
        type=int,
        dest="pdf_workers",
        help="Número de workers no modo paralelo (default: 3).",
    )
    parser.add_argument(
        "--pdf-retries",
        type=int,
        dest="pdf_retries",
        help="Número de tentativas por processo (default: 3).",
    )

    return parser.parse_args(argv)


def _parse_list_argument(cli_values: Optional[List[str]], env_value: Optional[str]) -> List[str]:
    """Combina valores vindos da CLI e das variáveis de ambiente em uma lista."""
    values: List[str] = []
    if cli_values:
        values.extend(cli_values)
    elif env_value:
        values.extend([item.strip() for item in env_value.split(",") if item.strip()])
    return [v for v in (val.strip() for val in values) if v]


def _parse_categorias(cli_values: Optional[List[str]], env_value: Optional[str]) -> Optional[Set[str]]:
    """Normaliza categorias informadas pelo usuário, tratando sinônimos comuns."""
    valores = _parse_list_argument(cli_values, env_value)
    if not valores:
        return None
    categorias_map = {
        "recebidos": "Recebidos",
        "recebido": "Recebidos",
        "gerados": "Gerados",
        "gerado": "Gerados",
        "todos": "TODOS",
        "ambos": "TODOS",
    }
    categorias: Set[str] = set()
    for valor in valores:
        chave = valor.lower()
        mapped = categorias_map.get(chave)
        if mapped == "TODOS":
            return None
        if mapped in {"Recebidos", "Gerados"}:
            categorias.add(mapped)
    if not categorias or len(categorias) == 2:
        return None
    return categorias


def _parse_positive_int(value: Optional[str], label: str) -> Optional[int]:
    """Tenta converter valores positivos informados via string."""
    if not value:
        return None
    try:
        numero = int(value)
        if numero < 1:
            return None
        return numero
    except ValueError:
        return None


def build_filter_options(settings: Settings, args: argparse.Namespace) -> FilterOptions:
    """Monta `FilterOptions` combinando argumentos CLI e variáveis de ambiente."""
    _ = settings  # reservado para futuras customizações por organização
    env = os.environ
    visualizacao_cli: Optional[str] = args.filtro_visualizados or args.filtro_nao_visualizados

    visualizacao_env = env.get("SEI_FILTRO_VISUALIZACAO")
    visualizacao = visualizacao_cli
    if visualizacao is None and visualizacao_env:
        valor = visualizacao_env.strip().lower()
        if valor in {"visualizados", "visualizado", "vistos"}:
            visualizacao = "visualizados"
        elif valor in {"nao_visualizados", "não_visualizados", "nao_visualizado", "pendentes", "novos"}:
            visualizacao = "nao_visualizados"

    categorias = _parse_categorias(args.categorias, env.get("SEI_FILTRO_CATEGORIA"))

    responsaveis = _parse_list_argument(args.responsaveis, env.get("SEI_FILTRO_RESPONSAVEL"))
    tipos = _parse_list_argument(args.tipos, env.get("SEI_FILTRO_TIPO"))
    marcadores = _parse_list_argument(args.marcadores, env.get("SEI_FILTRO_MARCADOR"))

    com_documentos_novos = args.com_documentos_novos
    if com_documentos_novos is None:
        com_documentos_novos = _str_to_bool(env.get("SEI_FILTRO_DOCS_NOVOS"))

    com_anotacoes = args.com_anotacoes
    if com_anotacoes is None:
        com_anotacoes = _str_to_bool(env.get("SEI_FILTRO_ANOTACOES"))

    limite = args.limite
    if limite is None and env.get("SEI_FILTRO_LIMITE"):
        try:
            limite = int(env["SEI_FILTRO_LIMITE"])
        except ValueError:
            limite = None
    if limite is not None and limite < 1:
        limite = None

    exportar_xlsx = args.exportar_xlsx or env.get("SEI_EXPORTAR_XLSX")

    categorias_normalizadas = None if categorias is None else {c for c in categorias}

    return FilterOptions(
        visualizacao=visualizacao,  # type: ignore[arg-type]
        categorias=None if categorias_normalizadas is None else {c for c in categorias_normalizadas},  # type: ignore[arg-type]
        responsaveis=responsaveis,
        tipos=tipos,
        marcadores=marcadores,
        com_documentos_novos=com_documentos_novos,
        com_anotacoes=com_anotacoes,
        limite=limite,
        exportar_xlsx=exportar_xlsx,
    )


def build_pagination_options(args: argparse.Namespace) -> PaginationOptions:
    """Cria opções de paginação considerando limites específicos por categoria."""
    env = os.environ

    def _sanitize_cli(value: Optional[int]) -> Optional[int]:
        if value is None or value < 1:
            return None
        return value

    max_receb_cli = _sanitize_cli(getattr(args, "paginas_recebidos", None))
    max_ger_cli = _sanitize_cli(getattr(args, "paginas_gerados", None))
    max_total_cli = _sanitize_cli(getattr(args, "paginas_max", None))

    max_receb_env = _parse_positive_int(env.get("SEI_PAGINAS_RECEBIDOS"), "SEI_PAGINAS_RECEBIDOS")
    max_ger_env = _parse_positive_int(env.get("SEI_PAGINAS_GERADOS"), "SEI_PAGINAS_GERADOS")
    max_total_env = _parse_positive_int(env.get("SEI_PAGINAS_MAX"), "SEI_PAGINAS_MAX")

    return PaginationOptions(
        max_paginas_recebidos=max_receb_cli if max_receb_cli is not None else max_receb_env,
        max_paginas_gerados=max_ger_cli if max_ger_cli is not None else max_ger_env,
        max_paginas_total=max_total_cli if max_total_cli is not None else max_total_env,
    )


def build_enrichment_options(settings: Settings, args: argparse.Namespace) -> EnrichmentOptions:
    """Define comportamento de enriquecimento (coleta de documentos, histórico, iframes)."""
    env = os.environ

    coletar_documentos = bool(args.coletar_documentos)
    if not coletar_documentos:
        coletar_documentos = _str_to_bool(env.get("SEI_COLETAR_DOCUMENTOS")) is True

    dump_iframes = bool(args.dump_iframes)
    if not dump_iframes:
        dump_iframes = _str_to_bool(env.get("SEI_DUMP_IFRAMES")) is True

    limite_doc = args.limite_processos_documentos
    if limite_doc is None:
        limite_doc = _parse_positive_int(env.get("SEI_LIMITE_PROCESSOS_DOCUMENTOS"), "SEI_LIMITE_PROCESSOS_DOCUMENTOS")
    if limite_doc is not None and limite_doc < 1:
        limite_doc = None

    dump_limite = args.dump_iframes_limite
    if dump_limite is None:
        dump_limite = _parse_positive_int(env.get("SEI_DUMP_IFRAMES_LIMITE"), "SEI_DUMP_IFRAMES_LIMITE")
    if dump_limite is not None and dump_limite < 1:
        dump_limite = None

    dump_dir_value = args.dump_iframes_dir or env.get("SEI_DUMP_IFRAMES_DIR")
    dump_dir_path: Optional[Path] = None
    if dump_dir_value:
        candidate = Path(dump_dir_value).expanduser()
        if not candidate.is_absolute():
            candidate = settings.data_dir / dump_dir_value
        dump_dir_path = candidate

    if dump_iframes and dump_limite is None:
        dump_limite = 5

    if dump_iframes:
        coletar_documentos = True
        if dump_limite is not None and (limite_doc is None or dump_limite > limite_doc):
            limite_doc = dump_limite

    salvar_historico = bool(args.salvar_historico)
    if not salvar_historico:
        salvar_historico = _str_to_bool(env.get("SEI_SALVAR_HISTORICO")) is True

    historico_value = args.historico_arquivo or env.get("SEI_HISTORICO_ARQUIVO")
    if historico_value:
        historico_path = Path(historico_value).expanduser()
        if not historico_path.is_absolute():
            historico_path = settings.data_dir / historico_value
    else:
        historico_path = settings.historico_path

    return EnrichmentOptions(
        coletar_documentos=coletar_documentos,
        limite_documentos=limite_doc,
        dump_iframes=dump_iframes,
        dump_iframes_limite=dump_limite,
        dump_iframes_dir=dump_dir_path,
        salvar_historico=salvar_historico,
        historico_arquivo=historico_path,
    )


def build_pdf_download_options(args: argparse.Namespace) -> PDFDownloadOptions:
    """Interpreta opções para geração/baixar PDFs, inclusive limites e paralelismo."""
    env = os.environ

    habilitado = bool(args.download_lote) or _str_to_bool(env.get("SEI_DOWNLOAD_LOTE")) is True

    limite = args.max_processos_pdf
    if limite is None:
        limite = _parse_positive_int(env.get("SEI_MAX_PROCESSOS_PDF"), "SEI_MAX_PROCESSOS_PDF")

    diretorio_value = args.pdf_dir or env.get("SEI_PDF_DIR")
    diretorio_path = Path(diretorio_value).expanduser() if diretorio_value else None

    paralelo = bool(args.pdf_paralelo) or _str_to_bool(env.get("SEI_PDF_PARALELO")) is True

    workers = args.pdf_workers if args.pdf_workers and args.pdf_workers > 0 else None
    if workers is None:
        workers_env = _parse_positive_int(env.get("SEI_PDF_WORKERS"), "SEI_PDF_WORKERS")
        workers = workers_env if workers_env else 3

    tentativas = args.pdf_retries if args.pdf_retries and args.pdf_retries > 0 else None
    if tentativas is None:
        retries_env = _parse_positive_int(env.get("SEI_PDF_RETRIES"), "SEI_PDF_RETRIES")
        tentativas = retries_env if retries_env else 3

    return PDFDownloadOptions(
        habilitado=habilitado,
        limite_processos=limite,
        diretorio_saida=diretorio_path,
        paralelo=paralelo,
        workers=workers,
        tentativas=tentativas,
    )

