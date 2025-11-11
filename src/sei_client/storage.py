"""Persistência de processos e exportação para formatos como JSON e Excel."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook

from .config import Settings
from .models import Processo

log = logging.getLogger(__name__)


def processo_para_dict(processo: Processo) -> Dict[str, Any]:
    """Converte os campos relevantes de `Processo` para um dicionário serializável."""
    return {
        "numero_processo": processo.numero_processo,
        "id_procedimento": processo.id_procedimento,
        "url": processo.url,
        "visualizado": processo.visualizado,
        "categoria": processo.categoria,
        "titulo": processo.titulo,
        "tipo_especificidade": processo.tipo_especificidade,
        "responsavel_nome": processo.responsavel_nome,
        "responsavel_cpf": processo.responsavel_cpf,
        "marcadores": processo.marcadores,
        "tem_documentos_novos": processo.tem_documentos_novos,
        "tem_anotacoes": processo.tem_anotacoes,
        "hash": processo.hash,
        "documentos": [asdict(doc) for doc in processo.documentos],
        "eh_sigiloso": processo.eh_sigiloso,
        "assinantes": processo.assinantes,
        "metadados": processo.metadados,
    }


def carregar_historico_processos(settings: Settings, caminho: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Lê o histórico salvo de processos a partir de um arquivo JSON, se existir."""
    path = Path(caminho or settings.historico_path).expanduser()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
        log.warning("Formato inesperado no histórico %s; retornando vazio.", path)
    except Exception as exc:
        log.warning("Erro ao carregar histórico %s: %s", path, exc)
    return {}


def salvar_historico_processos(settings: Settings, processos: List[Processo], caminho: Optional[Path] = None) -> Path:
    """Persiste o histórico de processos em um arquivo JSON organizado por ID."""
    path = Path(caminho or settings.historico_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    dados: Dict[str, Dict[str, Any]] = {}
    for processo in processos:
        chave = processo.id_procedimento or processo.numero_processo
        if not chave:
            continue
        dados[chave] = processo_para_dict(processo)

    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(dados, handle, ensure_ascii=False, indent=2)
        log.info("Histórico salvo em %s (%s processo(s)).", path, len(dados))
    except Exception as exc:
        log.error("Erro ao salvar histórico %s: %s", path, exc)
    return path


def exportar_processos_para_excel(processos: List[Processo], caminho: str) -> Optional[str]:
    """Gera uma planilha Excel com o resumo dos processos filtrados."""
    if not processos:
        log.info("Nenhum processo para exportar em Excel.")
        return None

    path = Path(caminho).expanduser()
    if path.is_dir():
        path = path / "processos_filtrados.xlsx"
    elif path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")

    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet("Processos")
    else:
        ws.title = "Processos"

    cabecalho = [
        "Número do Processo",
        "Categoria",
        "Visualizado",
        "Título",
        "Tipo/Especificidade",
        "Responsável",
        "CPF Responsável",
        "Marcadores",
        "Documentos Novos",
        "Anotações",
        "ID Procedimento",
        "Hash",
        "URL",
    ]
    ws.append(cabecalho)

    for proc in processos:
        ws.append(
            [
                proc.numero_processo,
                proc.categoria,
                "Sim" if proc.visualizado else "Não",
                proc.titulo or "",
                proc.tipo_especificidade or "",
                proc.responsavel_nome or "",
                proc.responsavel_cpf or "",
                ", ".join(proc.marcadores),
                "Sim" if proc.tem_documentos_novos else "Não",
                "Sim" if proc.tem_anotacoes else "Não",
                proc.id_procedimento,
                proc.hash,
                proc.url,
            ]
        )

    wb.save(path)
    log.info("Planilha Excel gerada: %s", path)
    return str(path)

