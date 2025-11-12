# Arquitetura do Pacote `sei_client`

## Visão Geral

O projeto adota uma arquitetura modular em torno do pacote `sei_client`, que encapsula toda a interação com o SEI em camadas especializadas. O alvo é fornecer uma base sólida para automações, testes e futuras extensões (ex.: APIs, workers, integrações com outros sistemas).

```
             ┌──────────┐
             │ CLI / UI │
             └────┬─────┘
                  │
            ┌─────▼─────┐
            │ SeiClient │  ← fachada orquestra fluxos
            └─┬───┬───┬─┘
              │   │   │
         ┌────▼┐ ┌▼───▼┐ ┌────────┐
         │auth │ │processes│      │
         │http │ │documents│ ...  │
         └─────┘ └────────┘ └─────┘
```

## Componentes Principais

| Módulo              | Responsabilidade                                                                                  |
|---------------------|---------------------------------------------------------------------------------------------------|
| `config.py`         | Carrega variáveis de ambiente, diretórios padrão e configura logging.                             |
| `http.py`           | Cria sessões `requests`, monta cabeçalhos e lida com salvamento condicional de HTML para debug.   |
| `auth.py`           | Fluxo de login, verificação/troca automática de unidade SEI e abertura da página de controle de processos. |
| `processes.py`      | Extração e paginação de processos, filtros e abertura de páginas individuais.                     |
| `documents.py`      | Parsing da árvore `ifrArvore`, coleta de metadados de documentos e assinaturas.                   |
| `pdf.py`            | Rotinas de geração e download de PDFs (sequencial ou paralelo).                                   |
| `storage.py`        | Exportação para Excel e persistência em JSON (histórico de processos).                            |
| `options.py`        | Construção de `FilterOptions`, `PaginationOptions`, etc. a partir de CLI/variáveis de ambiente.   |
| `cli.py`            | CLI oficial (`sei-client`), utilizando `SeiClient` para orquestrar fluxos end-to-end.             |
| `client.py`         | Fachada de alto nível: autentica, coleta processos, enriquece documentos e dispara downloads.     |

## Fluxos de Alto Nível

1. **Autenticação**
   - `SeiClient.login()` → `auth.login_sei()` garante sessão autenticada e obtém HTML de controle.
   - Se `SEI_UNIDADE` estiver configurada, `auth.obter_unidade_atual()` verifica a unidade atual e, se diferente, `auth.selecionar_unidade_sei()` realiza a troca automática antes de prosseguir.

2. **Coleta de processos**
   - `SeiClient.collect_processes()` usa `processes.coletar_processos()` para aplicar filtros e paginação.

3. **Enriquecimento de documentos**
   - `SeiClient.enrich_processes()` chama `documents.enriquecer_processos()` para abrir `ifrArvore`, coletar metadados e, opcionalmente, fazer dumps HTML.

4. **Persistência e exportação**
   - `storage.salvar_historico_processos()` guarda snapshot em JSON; `storage.exportar_processos_para_excel()` gera planilhas analíticas.

5. **Geração de PDFs**
   - `SeiClient.download_pdfs()` (modo lote) ou `SeiClient.generate_pdf()` (processo único) reutilizam `pdf.py`.

## Testabilidade

- Suites unitárias usam `MagicMock` e fixtures sintéticas (sem dados sensíveis).
- `options.py` centraliza o parsing de argumentos, facilitando a criação de casos de teste para combinações de filtros.
- Cada módulo evita efeitos colaterais diretos, permitindo mocks isolados de rede e IO.

## Extensibilidade

- **Novos canais (ex.: API REST):** reutilize `SeiClient` para atender outras interfaces.
- **Agendadores/Workers:** instancie `SeiClient` com `auto_configure_logging=False` e injete sessões customizadas (proxy, retries).
- **Persistência customizada:** componha novos serviços sobre `storage.py` ou substitua usando métodos de `SeiClient`.

## Convenções

- Diretórios de dados (`data/`, `pdfs/`, `saida/`) são ignorados por padrão. Geração é sempre local.
- Dumps de debug ficam em `data/debug/` quando `SEI_SAVE_DEBUG_HTML=1`.
- CLI oficial: `uv run sei-client ...` (script legado permanece disponível para backward compatibility).

