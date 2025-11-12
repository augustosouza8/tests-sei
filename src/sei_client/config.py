"""Carregamento de configurações e utilitários de ajuste para o cliente SEI."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

from .exceptions import SEIConfigError

load_dotenv()

DEFAULT_BASE_URL = "https://www.sei.mg.gov.br"
DEFAULT_LOGIN_PATH = "/sip/login.php?sigla_orgao_sistema=GOVMG&sigla_sistema=SEI&infra_url=L3NlaS8="


def _str_to_bool(value: Optional[str]) -> Optional[bool]:
    """Converte strings comuns em valores booleanos (`sim`, `não`, `true`, etc.)."""
    if value is None:
        return None
    value_norm = value.strip().lower()
    truthy = {"1", "true", "t", "yes", "y", "sim"}
    falsy = {"0", "false", "f", "no", "n", "nao", "não"}
    if value_norm in truthy:
        return True
    if value_norm in falsy:
        return False
    return None


@dataclass(frozen=True)
class Settings:
    """Representa a configuração de execução do cliente SEI."""

    orgao_value: str = field()
    unidade_value: str = field()
    base_url: str = DEFAULT_BASE_URL
    login_path: str = DEFAULT_LOGIN_PATH
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("SEI_DATA_DIR", "data")))
    save_debug_html: bool = field(default_factory=lambda: _str_to_bool(os.environ.get("SEI_SAVE_DEBUG_HTML")) is True)
    debug_enabled: bool = field(default_factory=lambda: _str_to_bool(os.environ.get("SEI_DEBUG")) is True)

    @property
    def login_url(self) -> str:
        """Retorna a URL completa de login com base na configuração atual."""
        return f"{self.base_url}{self.login_path}"

    @property
    def default_iframe_dir(self) -> Path:
        """Diretório padrão para persistir iframes salvos do SEI."""
        return self.data_dir / "iframes"

    @property
    def historico_path(self) -> Path:
        """Caminho padrão do arquivo JSON com histórico de processos."""
        return self.data_dir / "historico_processos.json"

    @property
    def unidade_alvo(self) -> str:
        """Unidade SEI que deve ficar ativa após o login."""
        unidade_norm = self.unidade_value.strip()
        return unidade_norm


def load_settings(overrides: Optional[Mapping[str, object]] = None) -> Settings:
    """
    Carrega configurações a partir de variáveis de ambiente com possíveis sobrescritas.
    
    Raises:
        SEIConfigError: Se SEI_ORGAO ou SEI_UNIDADE não estiverem definidas.
    """
    # Valida variáveis obrigatórias
    orgao_value = os.environ.get("SEI_ORGAO")
    unidade_value = os.environ.get("SEI_UNIDADE")
    
    if not orgao_value or not orgao_value.strip():
        raise SEIConfigError(
            "Variável de ambiente SEI_ORGAO é obrigatória. "
            "Defina-a com o código do órgão (ex: SEI_ORGAO=28)."
        )
    
    if not unidade_value or not unidade_value.strip():
        raise SEIConfigError(
            "Variável de ambiente SEI_UNIDADE é obrigatória. "
            "Defina-a com o nome da unidade SEI desejada (ex: SEI_UNIDADE=SEPLAG/AUTOMATIZAMG)."
        )
    
    # Aplica overrides se fornecidos
    if overrides:
        orgao_value = str(overrides.get("orgao_value", orgao_value))
        unidade_value = str(overrides.get("unidade_value", unidade_value))
    
    base = Settings(
        orgao_value=orgao_value.strip(),
        unidade_value=unidade_value.strip(),
    )
    
    if not overrides:
        return base
    
    data = asdict(base)
    data.update(overrides)
    return Settings(**data)  # type: ignore[arg-type]


def configure_logging(settings: Settings) -> logging.Logger:
    """Configura o logging global de acordo com o modo debug das configurações."""
    level = logging.DEBUG if settings.debug_enabled else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("sei-client")

