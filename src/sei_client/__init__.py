"""Facade para facilitar o consumo do cliente SEI como pacote Python."""

from .client import SeiClient, create_client
from .config import Settings, load_settings
from .models import (
    Documento,
    EnrichmentOptions,
    FilterOptions,
    PDFDownloadOptions,
    PDFDownloadResult,
    PaginationOptions,
    Processo,
)
from .storage import carregar_historico_processos, exportar_processos_para_excel, salvar_historico_processos

__all__ = [
    "SeiClient",
    "create_client",
    "Settings",
    "load_settings",
    "Documento",
    "Processo",
    "FilterOptions",
    "PaginationOptions",
    "EnrichmentOptions",
    "PDFDownloadOptions",
    "PDFDownloadResult",
    "carregar_historico_processos",
    "salvar_historico_processos",
    "exportar_processos_para_excel",
]

