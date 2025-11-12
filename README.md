# Tests API SEI

Projeto para interagir com o sistema SEI (Sistema Eletrônico de Informações) do Governo de Minas Gerais.

## 🚀 Configuração Inicial

### Pré-requisitos

- Python >= 3.13 (o `uv` instala automaticamente se necessário)
- `uv` instalado ([instruções de instalação](https://github.com/astral-sh/uv))

### Passos para começar

1. **Instalar dependências:**
   ```bash
   uv sync
   ```
   Isso criará um ambiente virtual (`.venv`) e instalará todas as dependências automaticamente, além de expor o entrypoint da CLI (`sei-client`) para uso via `uv run`.

2. **Configurar variáveis de ambiente:**

   **Opção 1: Usando arquivo .env (Recomendado)**
   
   Copie o arquivo de exemplo e preencha com suas credenciais:
   ```bash
   # Copie o arquivo de exemplo
   cp .env.example .env
   
   # Edite o arquivo .env com suas credenciais
   nano .env  # ou use seu editor preferido
   ```
   
   Ou crie o arquivo `.env` manualmente na raiz do projeto com as variáveis obrigatórias:
   ```env
   SEI_USER=seu_login_aqui
   SEI_PASS=sua_senha_aqui
   SEI_ORGAO=28  # obrigatório - código do órgão
   SEI_UNIDADE=SEPLAG/AUTOMATIZAMG  # obrigatório - nome da unidade SEI
   SEI_DEBUG=1  # opcional, para logs detalhados
   SEI_SAVE_DEBUG_HTML=1  # opcional, salva HTMLs para debug
   ```
   
   **Nota:** O arquivo `.env.example` contém todas as variáveis disponíveis com comentários explicativos.

   **Opção 2: Variáveis de ambiente no terminal**
   
   No macOS/Linux (zsh/bash):
   ```bash
   export SEI_USER="SEU_LOGIN"
   export SEI_PASS="SUA_SENHA"
   export SEI_ORGAO="28"  # obrigatório
   export SEI_UNIDADE="SEPLAG/AUTOMATIZAMG"  # obrigatório
   export SEI_DEBUG="1"  # opcional
   export SEI_SAVE_DEBUG_HTML="1"  # opcional
   ```
   
   No Windows (PowerShell):
   ```powershell
   $env:SEI_USER="SEU_LOGIN"
   $env:SEI_PASS="SUA_SENHA"
   $env:SEI_ORGAO="28"  # obrigatório
   $env:SEI_UNIDADE="SEPLAG/AUTOMATIZAMG"  # obrigatório
   $env:SEI_DEBUG="1"  # opcional
   $env:SEI_SAVE_DEBUG_HTML="1"  # opcional
   ```

3. **Executar o script principal:**
   ```bash
   # Acessar processos e gerar PDF
   uv run acessar_processos_sei.py
   ```

## 📂 Artefatos Gerados Localmente

- Os diretórios `data/`, `pdfs/` e `saida/` são ignorados pelo controle de versão. Eles armazenam históricos, dumps HTML e documentos produzidos durante a execução.
- Gere seus próprios artefatos executando os comandos do projeto (por exemplo `uv run acessar_processos_sei.py --salvar-historico --dump-iframes --download-lote`).
- Ao compartilhar exemplos, substitua dados sensíveis por valores fictícios antes de salvá-los no repositório.

## 📁 Estrutura do Projeto

- `src/sei_client/`
  - `client.py` – fachada de alto nível (`SeiClient`)
  - `config.py`, `auth.py`, `http.py`, `processes.py`, `documents.py`, `pdf.py`, `storage.py` – módulos especializados por domínio
  - `cli.py` – ponto de entrada da CLI (`sei-client`)
- `acessar_processos_sei.py` – compatibilidade legada; delega para `sei_client.cli`
- `tests/` – suíte de testes com fixtures sintéticas e mocks de rede

📄 Consulte `docs/architecture.md` para uma visão detalhada da divisão de responsabilidades e dos fluxos internos.

## ✨ Funcionalidades Principais

### `acessar_processos_sei.py`

Script refatorado e modularizado que oferece:

#### 1. **Login Automatizado**
- Autenticação no SEI com validação robusta
- Verificação de cookies de sessão
- **Troca automática de unidade SEI**: O sistema sempre verifica a unidade atual após o login e, se diferente da configurada em `SEI_UNIDADE` (obrigatória), troca automaticamente para a unidade desejada
- Tratamento de erros (credenciais inválidas, bloqueios, etc.)

**Como funciona a troca automática de unidade:**
- Após o login bem-sucedido, o sistema verifica qual unidade SEI está ativa
- Como `SEI_UNIDADE` é obrigatória, o sistema sempre:
  1. Carrega a página de seleção de unidades disponíveis
  2. Localiza a unidade desejada na lista
  3. Seleciona e confirma a troca automaticamente
  4. Recarrega a página de controle para garantir estado consistente
- Se a troca falhar (unidade não encontrada, erro de rede, etc.), o sistema continua com a unidade atual e registra um aviso nos logs
- A comparação de nomes de unidade é case-insensitive e tolerante a espaços extras

#### 2. **Extração Completa de Processos**
Extrai processos de ambas as categorias (**Recebidos** e **Gerados**) com metadados completos:

- **Informações Básicas:**
  - Número do processo (canonizado)
  - ID do procedimento
  - URL de acesso
  - Hash de segurança

- **Status:**
  - Visualizado / Não visualizado
  - Categoria (Recebidos/Gerados)

- **Metadados:**
  - Título do processo (extraído do tooltip)
  - Tipo/Especificidade (ex: "RH: Estagiário", "Viagem: Prestação de Contas")
  - Responsável (nome e CPF, se atribuído)
  - Marcadores/Status (ex: "Aguardando assinaturas", "Simplificação")
  - Indicadores: documentos novos, anotações

#### 3. **Geração de PDF**
- Gera PDF completo do processo
- Download automático com nome baseado no número do processo
- Validação de tamanho e tipo de arquivo
- Tratamento robusto de erros e timeouts

#### 4. **Filtros via CLI / Variáveis**
- Flags opcionais para filtrar processos (`--filtro-nao-visualizados`, `--categoria`, `--responsavel`, `--tipo`, `--marcador`)
- Possibilidade de exigir documentos novos (`--com-documentos-novos`) ou anotações (`--com-anotacoes`)
- Controle de limite de resultados (`--limite 10`)
- Suporte equivalente via variáveis de ambiente (`SEI_FILTRO_*`)

#### 5. **Exportação para Excel**
- `--exportar-xlsx caminho.xlsx` gera planilha com todos os campos extraídos
- Ideal para análises externas (Excel, Power BI, Google Sheets)
- Pode ser automatizado com `SEI_EXPORTAR_XLSX`

#### 6. **Paginação Automática**
- Carrega todas as páginas de Recebidos/Gerados automaticamente
- Flags para limitar páginas (`--paginas-recebidos`, `--paginas-gerados`, `--paginas-max`)
- Valores equivalentes via `SEI_PAGINAS_*`
- Deduplicação automática dos processos em todas as páginas
- `coletar_processos` e `enriquecer_processos` reutilizáveis para integrações futuras

#### 7. **Coleta de Documentos & Dumps do iframe**
- `--coletar-documentos` processa o `ifrArvore` de cada processo e extrai metadados de cada documento (links de download/visualização, assinaturas, indicadores, sigilo, etc.)
- `--limite-processos-documentos N` restringe quantos processos serão abertos para coleta detalhada
- `--dump-iframes` salva o HTML bruto do iframe em `data/iframes/` (ideal para gerar exemplos e depurar variações)
- `--dump-iframes-limite N` e `--dump-iframes-dir caminho/` controlam a quantidade e o diretório dos dumps
- Dados ficam disponíveis em `processo.documentos` (lista de `Documento`)
- Cada `Documento` traz campos enriquecidos como `download_url`, `visualizacao_url`, `assinantes`, `eh_sigiloso` e `metadados['nivel_acesso']`

#### 8. **Histórico em JSON**
- `--salvar-historico` persiste os processos coletados (com documentos) em `data/historico_processos.json`
- `--historico-arquivo caminho.json` define um arquivo personalizado
- Diretório base configurável via `SEI_DATA_DIR`
- Utilitários públicos: `carregar_historico_processos()` e `salvar_historico_processos()`

#### 9. **Estrutura de Dados**
O script retorna objetos `Processo` (dataclass) com a seguinte estrutura:

```python
@dataclass
class Processo:
    numero_processo: str
    id_procedimento: str
    url: str
    visualizado: bool
    categoria: Literal["Recebidos", "Gerados"]
    titulo: Optional[str]
    tipo_especificidade: Optional[str]
    responsavel_nome: Optional[str]
    responsavel_cpf: Optional[str]
    marcadores: List[str]
    tem_documentos_novos: bool
    tem_anotacoes: bool
    hash: str
    documentos: List["Documento"]
    eh_sigiloso: bool
    assinantes: List[str]
    metadados: Dict[str, Any]


@dataclass
class Documento:
    id_documento: str
    titulo: Optional[str]
    tipo: Optional[str]
    url: Optional[str]
    hash: Optional[str]
    download_url: Optional[str]
    visualizacao_url: Optional[str]
    indicadores: List[str]
    assinantes: List[str]
    eh_sigiloso: bool
    possui_assinaturas: bool
    eh_novo: bool
    metadados: Dict[str, Any]
```

#### 10. **Download em Lote de PDFs**
- `--download-lote` aciona o modo de download em massa dos processos filtrados
- `--max-processos-pdf N` limita quantos processos serão processados
- `--pdf-dir caminho/` define a pasta onde os PDFs serão gravados
- `--pdf-paralelo` e `--pdf-workers N` permitem processar múltiplos processos em paralelo (cada worker abre sua própria sessão)
- `--pdf-retries N` controla o número de tentativas por processo
- Resumo final inclui totais de sucesso/falha, tempo total e logs detalhados por processo

#### 11. **Logs e Debug**
- Logs informativos em cada etapa
- Opção de salvar HTMLs intermediários para debug (via `SEI_SAVE_DEBUG_HTML`)
- Mensagens de erro detalhadas com contexto

## 🔧 Comandos Úteis

```bash
# Ativar o ambiente virtual manualmente (se necessário)
source .venv/bin/activate  # macOS/Linux
# ou
.venv\Scripts\activate  # Windows

# Executar a CLI oficial
uv run sei-client --help

# Compatibilidade com o script legado (equivale ao comando acima)
uv run acessar_processos_sei.py

# Adicionar nova dependência
uv add nome-do-pacote

# Ver dependências instaladas
uv pip list
```

## 📝 Variáveis de Ambiente

| Variável | Descrição | Obrigatória | Default |
|----------|-----------|-------------|---------|
| `SEI_USER` | Login do SEI | ✅ Sim | - |
| `SEI_PASS` | Senha do SEI | ✅ Sim | - |
| `SEI_ORGAO` | Código do órgão | ✅ Sim | - |
| `SEI_UNIDADE` | Nome da unidade SEI desejada (ex: "SEPLAG/AUTOMATIZAMG") | ✅ Sim | - |
| `SEI_DEBUG` | Ativa logs detalhados (1/true/yes) | ❌ Não | - |
| `SEI_SAVE_DEBUG_HTML` | Salva HTMLs para debug (1/true/yes) | ❌ Não | - |
| `SEI_SIGLA_SISTEMA` | Sigla do sistema (para API SOAP) | ❌ Não | - |
| `SEI_IDENT_SERVICO` | Identificador do serviço (para API SOAP) | ❌ Não | - |
| `SEI_FILTRO_VISUALIZACAO` | `visualizados` ou `nao_visualizados` | ❌ Não | - |
| `SEI_FILTRO_CATEGORIA` | `recebidos`, `gerados` ou ambos (CSV) | ❌ Não | - |
| `SEI_FILTRO_RESPONSAVEL` | Lista CSV com substrings de responsável | ❌ Não | - |
| `SEI_FILTRO_TIPO` | Lista CSV de tipos/especificidade | ❌ Não | - |
| `SEI_FILTRO_MARCADOR` | Lista CSV de marcadores/status | ❌ Não | - |
| `SEI_FILTRO_DOCS_NOVOS` | `true` filtra processos com documentos novos | ❌ Não | - |
| `SEI_FILTRO_ANOTACOES` | `true` filtra processos com anotações | ❌ Não | - |
| `SEI_FILTRO_LIMITE` | Limite máximo de processos após filtros | ❌ Não | - |
| `SEI_EXPORTAR_XLSX` | Caminho para gerar automaticamente a planilha | ❌ Não | - |
| `SEI_PAGINAS_RECEBIDOS` | Máximo de páginas carregadas de Recebidos | ❌ Não | - |
| `SEI_PAGINAS_GERADOS` | Máximo de páginas carregadas de Gerados | ❌ Não | - |
| `SEI_PAGINAS_MAX` | Limite geral de páginas (aplica a ambos) | ❌ Não | - |
| `SEI_COLETAR_DOCUMENTOS` | `true` ativa coleta de documentos do iframe | ❌ Não | - |
| `SEI_LIMITE_PROCESSOS_DOCUMENTOS` | Limite de processos para coleta detalhada | ❌ Não | - |
| `SEI_DUMP_IFRAMES` | `true` salva HTMLs do iframe em disco | ❌ Não | - |
| `SEI_DUMP_IFRAMES_LIMITE` | Limite de iframes salvos quando ativo | ❌ Não | 5 |
| `SEI_DUMP_IFRAMES_DIR` | Diretório de saída dos iframes | ❌ Não | `data/iframes` |
| `SEI_SALVAR_HISTORICO` | `true` salva histórico em JSON | ❌ Não | - |
| `SEI_HISTORICO_ARQUIVO` | Caminho do arquivo de histórico | ❌ Não | `data/historico_processos.json` |
| `SEI_DATA_DIR` | Diretório base para dados persistentes | ❌ Não | `data` |
| `SEI_DOWNLOAD_LOTE` | `true` ativa download em lote sem passar flag CLI | ❌ Não | - |
| `SEI_MAX_PROCESSOS_PDF` | Limite de processos para o download em lote | ❌ Não | - |
| `SEI_PDF_DIR` | Diretório de saída dos PDFs gerados | ❌ Não | `.` |
| `SEI_PDF_PARALELO` | `true` habilita modo paralelo | ❌ Não | - |
| `SEI_PDF_WORKERS` | Número de workers no modo paralelo | ❌ Não | 3 |
| `SEI_PDF_RETRIES` | Tentativas por processo no download em lote | ❌ Não | 3 |

## 🎯 Exemplo de Uso

### Uso Básico

```bash
# 1. Configure as variáveis de ambiente obrigatórias
export SEI_USER="seu_login"
export SEI_PASS="sua_senha"
export SEI_ORGAO="28"  # obrigatório
export SEI_UNIDADE="SEPLAG/AUTOMATIZAMG"  # obrigatório

# 2. Execute o script
uv run acessar_processos_sei.py
```

### Uso com Troca Automática de Unidade

```bash
# Configure todas as variáveis obrigatórias
export SEI_USER="seu_login"
export SEI_PASS="sua_senha"
export SEI_ORGAO="28"  # obrigatório
export SEI_UNIDADE="SEPLAG/AUTOMATIZAMG"  # obrigatório - nome exato da unidade conforme aparece no SEI

# Execute o script - a troca será feita automaticamente se necessário
uv run acessar_processos_sei.py
```

**Nota:** O nome da unidade deve corresponder exatamente ao que aparece no sistema SEI (case-insensitive). Para descobrir o nome exato, você pode:
1. Fazer login manualmente no SEI
2. Clicar no link de unidade no topo da página
3. Verificar o nome exato na lista de unidades disponíveis

O script irá:
1. Fazer login no SEI
2. Verificar e trocar automaticamente para a unidade SEI configurada em `SEI_UNIDADE` (obrigatória)
3. Listar todos os processos (Recebidos e Gerados)
4. Exibir informações sobre processos não visualizados
5. Gerar PDF do primeiro processo da lista
6. Salvar o PDF com nome baseado no número do processo

### Saída Esperada

```
10:30:15 [INFO] Abrindo página de login…
10:30:16 [INFO] Enviando POST de login…
10:30:17 [INFO] Autenticado com sucesso.
10:30:17 [INFO] Acessando controle de processos: ...
10:30:17 [INFO] Unidade SEI atual: FHEMIG/DIRASS/GEPI/CIP/CFA
10:30:17 [INFO] Unidade SEI atual (FHEMIG/DIRASS/GEPI/CIP/CFA) difere da desejada (SEPLAG/AUTOMATIZAMG). Iniciando troca...
10:30:17 [INFO] Carregando página de seleção de unidades: ...
10:30:17 [INFO] Selecionando unidade SEI: SEPLAG/AUTOMATIZAMG (ID: 110000248)
10:30:18 [INFO] Unidade SEI alterada com sucesso para: SEPLAG/AUTOMATIZAMG
10:30:19 [INFO] Total de processos extraídos: 105 (70 Recebidos, 35 Gerados)
10:30:19 [INFO] Processos não visualizados: 15
10:30:19 [INFO]   - 1500.01.0310980/2025-88 (Recebidos, Não Visualizado)
10:30:19 [INFO]   - 1410.01.0000224/2024-76 (Recebidos, Não Visualizado)
...
10:30:20 [INFO] Abrindo processo: 1500.01.0427181/2025-29
10:30:21 [INFO] Carregando iframe (ifrArvore): ...
10:30:22 [INFO] Abrindo página de opções do PDF: ...
10:30:23 [INFO] Baixando arquivo: ...
10:30:25 [INFO] PDF salvo: processo_1500_01_0427181_2025-29.pdf (245.67 KB)
10:30:25 [INFO] PDF gerado com sucesso!
```

### Uso com filtros e exportação

```bash
uv run acessar_processos_sei.py \
  --filtro-nao-visualizados \
  --categoria recebidos \
  --responsavel "Clarisse" \
  --tipo "Estágio" \
  --marcador "assinatura" \
  --paginas-recebidos 2 \
  --limite 5 \
  --exportar-xlsx "./saida/processos_estagio.xlsx"
```

Esse comando:

1. Filtra apenas processos não visualizados na categoria **Recebidos**
2. Aplica substrings de responsável, tipo/especificidade e marcadores
3. Carrega no máximo 2 páginas de Recebidos
4. Limita a lista final a 5 processos
5. Exporta a planilha Excel para `./saida/processos_estagio.xlsx`
6. Gera o PDF somente do primeiro processo resultante

### Coletar documentos e salvar iframes para análise

```bash
uv run acessar_processos_sei.py \
  --coletar-documentos \
  --limite-processos-documentos 5 \
  --dump-iframes \
  --dump-iframes-limite 5 \
  --salvar-historico
```

Esse fluxo:

1. Abre até 5 processos filtrados e coleta metadados de cada documento (`processo.documentos`)
2. Salva HTMLs do iframe em `data/iframes/00N_NUMERO.html` para inspeção manual
3. Gera ou atualiza `data/historico_processos.json` com todos os campos coletados

### Download em lote de PDFs

```bash
uv run acessar_processos_sei.py \
  --download-lote \
  --max-processos-pdf 10 \
  --pdf-dir "./pdfs_estagio" \
  --pdf-retries 2
```

- Seleciona os processos conforme filtros e gera PDFs para até 10 processos
- Salva os arquivos no diretório informado e apresenta resumo de sucessos/falhas
- Use `--pdf-paralelo --pdf-workers 4` para habilitar downloads paralelos (cada worker abre nova sessão)