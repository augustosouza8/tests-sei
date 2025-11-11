"""Ponto de entrada de linha de comando para interagir com o cliente SEI."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from .client import SeiClient
from .config import load_settings
from .models import EnrichmentOptions, FilterOptions, PDFDownloadOptions, PaginationOptions, Processo
from .options import (
    build_enrichment_options,
    build_filter_options,
    build_pdf_download_options,
    build_pagination_options,
    parse_cli_args,
)

log = logging.getLogger("sei-client")


def run(argv: Optional[list[str]] = None) -> int:
    """Executa o fluxo principal da CLI: login, filtros, enriquecimento e PDFs."""
    args = parse_cli_args(argv)
    settings = load_settings()
    client = SeiClient(settings=settings)

    try:
        client.login()

        filtros: FilterOptions = build_filter_options(settings, args)
        paginacao: PaginationOptions = build_pagination_options(args)
        enrichment: EnrichmentOptions = build_enrichment_options(settings, args)
        pdf_options: PDFDownloadOptions = build_pdf_download_options(args)

        processos, processos_filtrados = client.collect_processes(filtros, paginacao)
        if not processos:
            return 0

        if filtros.exportar_xlsx and processos_filtrados:
            try:
                destination = client.export_to_excel(processos_filtrados, filtros.exportar_xlsx)
                if destination:
                    log.info("Processos exportados para: %s", destination)
            except Exception:
                log.exception("Erro ao exportar planilha Excel.")

        if not processos_filtrados:
            return 0

        nao_visualizados = [p for p in processos_filtrados if not p.visualizado]
        if nao_visualizados:
            log.info("Processos não visualizados dentro dos filtros: %s", len(nao_visualizados))
            for processo in nao_visualizados[:5]:
                log.info("  - %s", processo)

        if enrichment.coletar_documentos or enrichment.dump_iframes:
            processos_filtrados = client.enrich_processes(processos_filtrados, enrichment)
            if enrichment.coletar_documentos:
                total_documentos = sum(len(proc.documentos) for proc in processos_filtrados)
                media = total_documentos / len(processos_filtrados) if processos_filtrados else 0
                log.info("Documentos coletados: %s (média %.2f por processo).", total_documentos, media)
                if enrichment.salvar_historico:
                    client.save_history(processos_filtrados, enrichment.historico_arquivo)

        if pdf_options.habilitado:
            resultados = client.download_pdfs(processos_filtrados, pdf_options)
            if not resultados:
                return 10
            if not any(r.sucesso for r in resultados):
                log.error("Nenhum PDF gerado com sucesso no modo lote.")
                return 10
            log.info("Download em lote concluído. Encerrando execução.")
            return 0

        primeiro: Processo = processos_filtrados[0]
        destino_dir = str(pdf_options.diretorio_saida) if pdf_options.diretorio_saida else None
        resultado_pdf = client.generate_pdf(primeiro, diretorio_saida=destino_dir)
        if resultado_pdf.sucesso and resultado_pdf.caminho:
            log.info("PDF gerado com sucesso! (%s)", resultado_pdf.caminho)
            return 0

        log.error("Erro ao gerar PDF: %s", resultado_pdf.erro or "desconhecido")
        return 10

    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - proteção CLI
        log.exception("Erro inesperado: %s", exc)
        return 99
    finally:
        client.close()


def main(argv: Optional[list[str]] = None) -> None:
    """Wrapper que encerra o programa com o código de retorno da execução."""
    sys.exit(run(argv))


if __name__ == "__main__":
    main()

