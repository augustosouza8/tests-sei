class SEIError(Exception):
    """Exceção base para erros do SEI."""


class SEIConfigError(SEIError):
    """Erro relacionado à configuração do cliente SEI."""


class SEILoginError(SEIError):
    """Erro relacionado ao login no SEI."""


class SEIProcessoError(SEIError):
    """Erro relacionado a processos do SEI."""


class SEIPDFError(SEIError):
    """Erro relacionado à geração/download de PDFs."""

