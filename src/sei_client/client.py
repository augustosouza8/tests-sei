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
        self._unidade_atual: Optional[str] = None
        self._trocar_unidade_url: Optional[str] = None
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
        unidade_atual, trocar_url = auth.obter_unidade_atual(self.settings, controle_html)
        self._unidade_atual = unidade_atual
        self._trocar_unidade_url = trocar_url
        if unidade_atual:
            log.info("Unidade SEI atual: %s", unidade_atual)

        # Verifica se é necessário trocar a unidade SEI
        if self.settings.unidade_alvo.strip().upper() != (unidade_atual or "").strip().upper():
            log.info(
                "Unidade SEI atual (%s) difere da desejada (%s). Iniciando troca...",
                unidade_atual or "desconhecida",
                self.settings.unidade_alvo,
            )

            if not trocar_url:
                log.warning("URL de troca de unidade não disponível. Continuando com a unidade atual.")
            else:
                try:
                    # Carrega a página de seleção de unidades
                    html_selecao = auth.carregar_pagina_selecao_unidades(
                        self.session, self.settings, trocar_url
                    )

                    # Seleciona a unidade desejada
                    sucesso, html_resultado = auth.selecionar_unidade_sei(
                        self.session,
                        self.settings,
                        html_selecao,
                        self.settings.unidade_alvo,
                        trocar_url,
                    )

                    if sucesso and html_resultado:
                        # Atualiza o HTML e URL do controle após a troca
                        # Tenta encontrar a URL de controle no HTML resultante
                        nova_url_controle = auth.descobrir_url_controle_do_html(self.settings, html_resultado)
                        if nova_url_controle:
                            # Recarrega a página de controle para garantir estado consistente
                            controle_html, controle_url = auth.abrir_controle(
                                self.session, self.settings, html_resultado
                            )
                            self._controle_html = controle_html
                            self._controle_url = controle_url

                            # Verifica novamente a unidade após a troca
                            nova_unidade, nova_trocar_url = auth.obter_unidade_atual(
                                self.settings, controle_html
                            )
                            self._unidade_atual = nova_unidade
                            self._trocar_unidade_url = nova_trocar_url
                            log.info("Unidade SEI alterada com sucesso para: %s", nova_unidade or self.settings.unidade_alvo)
                        else:
                            # Se não encontrou URL de controle, usa o HTML resultante diretamente
                            self._controle_html = html_resultado
                            log.info("Unidade SEI alterada. HTML atualizado.")
                    else:
                        log.warning(
                            "Falha ao trocar unidade SEI para %s. Continuando com a unidade atual (%s).",
                            self.settings.unidade_alvo,
                            unidade_atual or "desconhecida",
                        )
                except SEIProcessoError as exc:
                    log.error("Erro ao trocar unidade SEI: %s. Continuando com a unidade atual.", exc)
                except Exception as exc:
                    log.error("Erro inesperado ao trocar unidade SEI: %s. Continuando com a unidade atual.", exc)

        self._logged_in = True
        if self.settings.save_debug_html:
            try:
                self.dump_controle_html()
            except Exception as exc:  # pragma: no cover - apenas log defensivo
                log.warning("Falha ao salvar HTML do controle pós-login: %s", exc)

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

    def dump_controle_html(self, destino: Optional[Path] = None) -> Path:
        """Salva o HTML atual da página de controle para inspeção manual."""
        self._ensure_login()
        assert self._controle_html is not None
        destino_path = Path(destino).expanduser() if destino else self.settings.data_dir / "debug" / "controle_pos_login.html"
        destino_path.parent.mkdir(parents=True, exist_ok=True)
        destino_path.write_text(self._controle_html, encoding="iso-8859-1")
        log.info("HTML do controle salvo em %s", destino_path)
        return destino_path


def create_client(auto_configure_logging: bool = True) -> SeiClient:
    """Cria uma instância de `SeiClient` com configuração de logging opcional."""
    return SeiClient(auto_configure_logging=auto_configure_logging)

