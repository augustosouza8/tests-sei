"""Cliente de alto nível para interagir com o SEI (Sistema Eletrônico de Informações)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from . import auth, documents, pdf, processes, storage
from .config import Settings, configure_logging, load_settings
from .exceptions import SEILoginError, SEIProcessoError
from .http import create_session
from .models import (
    EnrichmentOptions,
    FilterOptions,
    PDFDownloadOptions,
    PDFDownloadResult,
    PaginationOptions,
    Processo,
)

log = logging.getLogger(__name__)


class SeiClient:
    """Encapsula a autenticação e as operações de coleta de dados do SEI."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session: Optional[requests.Session] = None,
        auto_configure_logging: bool = True,
    ) -> None:
        """Inicializa o cliente com as configurações e sessão HTTP fornecidas."""
        self.settings = settings or load_settings()
        if auto_configure_logging:
            configure_logging(self.settings)
        self.session = session or create_session(self.settings)
        self._login_html: Optional[str] = None
        self._controle_html: Optional[str] = None
        self._controle_url: Optional[str] = None
        self._logged_in = False

    def login(self, user: Optional[str] = None, password: Optional[str] = None) -> None:
        """Realiza o login no SEI utilizando usuário/senha configurados."""
        user = user or os.environ.get("SEI_USER")
        password = password or os.environ.get("SEI_PASS")
        if not user or not password:
            raise SEILoginError("Defina SEI_USER e SEI_PASS para autenticação.")

        ok, html_login = auth.login_sei(self.session, self.settings, user, password)
        if not ok:
            raise SEILoginError("Falha no login.")

        self._login_html = html_login

        controle_html, controle_url = auth.abrir_controle(self.session, self.settings, html_login)
        self._controle_html = controle_html
        self._controle_url = controle_url
        self._logged_in = True

    def _ensure_login(self) -> None:
        """Garante que o cliente esteja autenticado antes de prosseguir."""
        if not self._logged_in or not self._controle_html or not self._controle_url:
            raise SEILoginError("É necessário autenticar antes de realizar esta operação.")

    def collect_processes(
        self,
        filtros: FilterOptions,
        paginacao: PaginationOptions,
    ) -> Tuple[List[Processo], List[Processo]]:
        """Busca processos no controle do SEI e aplica filtros de alto nível."""
        self._ensure_login()
        assert self._controle_html and self._controle_url
        return processes.coletar_processos(
            self.session,
            self.settings,
            filtros,
            paginacao,
            self._controle_html,
            self._controle_url,
        )

    def enrich_processes(
        self,
        processos_alvo: List[Processo],
        options: EnrichmentOptions,
    ) -> List[Processo]:
        """Carrega documentos e metadados adicionais para os processos informados."""
        if not options.coletar_documentos and not options.dump_iframes:
            return processos_alvo

        if options.dump_iframes and options.dump_iframes_dir is None:
            options.dump_iframes_dir = self.settings.default_iframe_dir

        return documents.enriquecer_processos(
            self.session,
            self.settings,
            processos_alvo,
            options,
            processes.abrir_processo,
        )

    def export_to_excel(self, processos_alvo: List[Processo], caminho: str) -> Optional[str]:
        """Exporta a lista de processos para um arquivo Excel."""
        return storage.exportar_processos_para_excel(processos_alvo, caminho)

    def save_history(self, processos_alvo: List[Processo], caminho: Optional[Path] = None) -> None:
        """Persiste o histórico dos processos em disco para consultas futuras."""
        storage.salvar_historico_processos(self.settings, processos_alvo, caminho)

    def download_pdfs(
        self,
        processos_alvo: List[Processo],
        options: PDFDownloadOptions,
    ) -> List[PDFDownloadResult]:
        """Baixa PDFs dos processos informados de acordo com as opções configuradas."""
        if not options.habilitado:
            log.debug("Opções de download em lote desativadas; nada a fazer.")
            return []
        return pdf.baixar_pdfs_em_lote(self.session, self.settings, processos_alvo, options)

    def generate_pdf(
        self,
        processo: Processo,
        diretorio_saida: Optional[str] = None,
    ) -> PDFDownloadResult:
        """Gera um PDF único para o processo informado."""
        destino = None if diretorio_saida is None else Path(diretorio_saida).expanduser()
        return pdf.gerar_pdf_processo(self.session, self.settings, processo, destino)

    def close(self) -> None:
        """Encerra a sessão HTTP aberta pelo cliente."""
        self.session.close()


def create_client(auto_configure_logging: bool = True) -> SeiClient:
    """Cria uma instância de `SeiClient` com configuração de logging opcional."""
    return SeiClient(auto_configure_logging=auto_configure_logging)

