"""Modelos de dados utilizados para representar processos, documentos e opções do SEI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set


@dataclass
class Documento:
    """Representa um documento listado dentro de um processo do SEI."""

    id_documento: str
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    url: Optional[str] = None
    hash: Optional[str] = None
    download_url: Optional[str] = None
    visualizacao_url: Optional[str] = None
    indicadores: List[str] = field(default_factory=list)
    assinantes: List[str] = field(default_factory=list)
    eh_sigiloso: bool = False
    possui_assinaturas: bool = False
    eh_novo: bool = False
    metadados: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Processo:
    """Modelo com metadados básicos de um processo retornado pelo SEI."""

    numero_processo: str
    id_procedimento: str
    url: str
    visualizado: bool
    categoria: Literal["Recebidos", "Gerados"]
    titulo: Optional[str] = None
    tipo_especificidade: Optional[str] = None
    responsavel_nome: Optional[str] = None
    responsavel_cpf: Optional[str] = None
    marcadores: List[str] = field(default_factory=list)
    tem_documentos_novos: bool = False
    tem_anotacoes: bool = False
    hash: str = ""
    documentos: List[Documento] = field(default_factory=list)
    eh_sigiloso: bool = False
    assinantes: List[str] = field(default_factory=list)
    metadados: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - apenas para logs
        """Retorna representação amigável para logs/debug."""
        status = "Visualizado" if self.visualizado else "Não Visualizado"
        return f"{self.numero_processo} ({self.categoria}, {status})"


@dataclass
class FilterOptions:
    """Opções de filtragem aplicadas após coletar os processos do SEI."""

    visualizacao: Optional[Literal["visualizados", "nao_visualizados"]] = None
    categorias: Optional[Set[Literal["Recebidos", "Gerados"]]] = None
    responsaveis: List[str] = field(default_factory=list)
    tipos: List[str] = field(default_factory=list)
    marcadores: List[str] = field(default_factory=list)
    com_documentos_novos: Optional[bool] = None
    com_anotacoes: Optional[bool] = None
    limite: Optional[int] = None
    exportar_xlsx: Optional[str] = None


@dataclass
class PaginationOptions:
    """Configuração para limitar a coleta a determinadas páginas de cada categoria."""

    max_paginas_recebidos: Optional[int] = None
    max_paginas_gerados: Optional[int] = None
    max_paginas_total: Optional[int] = None

    def limite_para(self, grupo: Literal["Recebidos", "Gerados"], total_paginas: int) -> int:
        """Calcula a quantidade máxima de páginas que devem ser percorridas."""
        limites: List[int] = []
        if self.max_paginas_total:
            limites.append(self.max_paginas_total)
        if grupo == "Recebidos" and self.max_paginas_recebidos:
            limites.append(self.max_paginas_recebidos)
        if grupo == "Gerados" and self.max_paginas_gerados:
            limites.append(self.max_paginas_gerados)
        if not limites:
            return total_paginas
        limite = min(limites)
        if limite < 1:
            return 1
        return min(total_paginas, limite)


@dataclass
class PaginationInfo:
    """Estrutura auxiliar com dados calculados de paginação do SEI."""

    total_registros: int
    pagina_atual: int
    total_paginas: int
    itens_por_pagina: int


@dataclass
class EnrichmentOptions:
    """Opcionalidades para enriquecimento dos processos com documentos e histórico."""

    coletar_documentos: bool = False
    limite_documentos: Optional[int] = None
    dump_iframes: bool = False
    dump_iframes_limite: Optional[int] = None
    dump_iframes_dir: Optional[Path] = None
    salvar_historico: bool = False
    historico_arquivo: Optional[Path] = None


@dataclass
class PDFDownloadOptions:
    """Parâmetros de configuração para o download de PDFs (único ou em lote)."""

    habilitado: bool = False
    limite_processos: Optional[int] = None
    diretorio_saida: Optional[Path] = None
    paralelo: bool = False
    workers: int = 3
    tentativas: int = 3


@dataclass
class PDFDownloadResult:
    """Resultado individual do download de PDF para um processo específico."""

    processo: Processo
    sucesso: bool
    caminho: Optional[Path] = None
    erro: Optional[str] = None
    tentativas: int = 0
    tempo_segundos: float = 0.0

