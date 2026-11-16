# 04 — Guardrails, Segurança e Dados Sensíveis

Parte de [SPEC.md](../../SPEC.md).

## 1. Modelo de ameaças (resumo)

| Ameaça | Vetor | Controle principal |
|---|---|---|
| Prompt injection indireta | texto de notícia com instruções | ADR 0004 (sem tools nos LLMs), G2 sanitização/delimitação, G3 |
| Alucinação de números/fatos | LLM inventa métricas ou notícias | G3 grounding determinístico, fail-closed |
| Injeção de SurrealQL / exfiltração | parâmetros ou LLM gerando consulta | sem consulta livre; **só variáveis** (`$uf`, `$start`…, nunca interpolação de string); G1 tipado; usuário `api_ro` de mínimo privilégio |
| Escalada/abuso no banco | credenciais únicas com poder total | usuários separados por banco e papel ([02](02-data-and-metrics.md) §2.2); root só no bootstrap; senhas via secret |
| Vazamento de dado pessoal | colunas sensíveis, texto livre, notícias com nomes | minimização no ingest, scrubber, supressão de célula pequena |
| Abuso de custo / DoS | loops, entradas grandes | G4 orçamento, rate limit, timeouts |
| SSRF / conteúdo malicioso | URLs de notícia | nenhum fetch de URL arbitrária; só API do provider (hosts fixos) |
| Vazamento de segredos | chaves em logs/imagem | segredos só por env/secret, nunca em imagem/log; scan no CI |
| Adulteração de evidência | edição da trilha | hash chain + `audit verify` |

## 2. Camadas de guardrail

Implementação: módulo `guardrails/`, cada guardrail = função pura `check(...) -> GuardrailVerdict(action, rule_id, details)` com `action ∈ {allow, sanitize, block}`. **Todo veredito vai à auditoria e a um contador OTel** (`srag.guardrail.verdicts{layer,rule,action}`).

### G1 — Entrada
- Schema estrito Pydantic (`extra="forbid"`): `uf ∈ {BR, 27 UFs}`, `as_of` entre 2019-01-01 e `max(DT_NOTIFIC)`, `window_days ∈ [7, 90]`.
- Nenhum texto livre do usuário chega ao LLM na PoC (superfície reduzida); se campo livre for adicionado → *Ask first* + G1b (injection/PII).
- Rate limit por IP/chave (middleware) e tamanho máximo de corpo.

### G2 — Notícias (dado não confiável)
- Allowlist/score de domínios (agências de saúde, grandes veículos; lista em arquivo versionado); fora da lista → descartado ou rebaixado.
- Filtros: idioma pt, janela de datas, relevância (palavras-chave SRAG/influenza/COVID/VSR), deduplicação por URL canônica/título.
- Sanitização: remove HTML/markup, caracteres de controle e Unicode invisível/bidi; trunca; **detector de instruções** (padrões como "ignore previous", "system prompt", chamadas de ferramenta) → artigo descartado + registro.
- Scrubber de PII (CPF, CNPJ, e-mail, telefone, nomes de pacientes quando detectáveis por padrão) no trecho antes de enviar ao LLM.
- Entrega ao LLM dentro de `<untrusted_news id="A1">…</untrusted_news>`, com instrução de sistema declarando-o dado.

### G3 — Saída (verificação da narrativa)
Todas determinísticas:
1. **Grounding numérico:** todo número/percentual/data no texto deve corresponder (com tolerância de arredondamento definida) a um valor do `MetricsPayload` referenciado em `metric_refs`; qualquer outro número ⇒ violação (exceto anos/ids permitidos por regex).
2. **Grounding de notícias:** cada `news_context` deve ter `article_refs` ⊆ artigos coletados; nenhuma URL/veículo fora do conjunto.
3. **Cobertura:** ≥ 1 comentário por M1–M4; `limitations` menciona proxies M3/M4 e maturidade quando aplicável.
4. **Política de conteúdo:** sem diagnóstico/prescrição/recomendação clínica individual, sem causalidade afirmada sem fonte, sem linguagem alarmista (lista de padrões + termos).
5. **PII scrub na saída** e checagem de tamanho/idioma.
Política: 1 retry com a lista de violações; persistindo ⇒ `NARRATIVE_REJECTED` → relatório só com métricas, gráficos e aviso.

### G4 — Orçamento e limites
`max_llm_calls=3`, `max_input_tokens`/`max_output_tokens` por chamada, `max_news_queries=3`, `max_articles=8`, timeout por nó e global (default 90 s), `recursion_limit` do grafo. Estouro ⇒ degradação sinalizada + auditoria.

## 3. Tratamento de dados sensíveis

| Dado | Política |
|---|---|
| Colunas do Open DATASUS | allowlist de 8 colunas (leitura remota com projeção: as demais nem saem da fonte) ([02](02-data-and-metrics.md) §3); o restante é descartado no ingest, antes de curar e de qualquer log |
| Linhas individuais | **nunca** enviadas ao LLM, a logs ou a traces; só agregados |
| Agregados pequenos | supressão `<5` em recortes secundários |
| Prompts/respostas LLM | armazenados na auditoria **somente como hash + versão** por padrão; texto completo apenas com `AUDIT_STORE_CONTENT=true` (dev) e passando pelo scrubber |
| Logs/traces | sem payloads; atributos limitados a ids, contagens, hashes; processador OTel de *redaction* no Collector como segunda barreira |
| Banco de dados | só agregados diários (sem linhas individuais) em `data`; `data` e `audit` somente-leitura para a API; `audit` append-only; consultas sempre parametrizadas; credenciais por papel; SurrealDB não exposto fora da rede interna do Compose (sem `ports:` no host em modo "prod-like") |
| Chaves dos provedores de LLM | `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`/`GEMINI_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY` (+ `TAVILY_API_KEY`) via env/secret, `SecretStr`, **somente a chave do provedor ativo é injetada** no container; nunca em logs/traces/auditoria |
| Segredos | `.env` fora do git (`.gitignore` já cobre), `.env.example` sem valores, Docker secrets/env em runtime, nunca `ARG`/`COPY` de segredos; `pydantic.SecretStr`; scan (gitleaks) no CI |
| LGPD | dados abertos já anonimizados pela fonte; mesmo assim minimização + risco de reidentificação por combinação de atributos (por isso sem município/idade/sexo nesta PoC); documentado no README |

## 4. Segurança de aplicação e container

- Imagem não-root, `read_only` filesystem com volumes explícitos (`/tmp` e `reports/` graváveis; a API não monta o staging `data/raw`), `cap_drop: [ALL]`, `no-new-privileges`, healthchecks, base `-slim` com tag fixa.
- Dependências pinadas (`uv.lock`), `pip-audit`/`uv audit` e Trivy no CI.
- Jinja2 com autoescape; CSP restritiva no HTML; cabeçalhos de segurança na API.
- Egress: app só fala com Collector, SurrealDB (rede `data`, `internal: true`), **o provedor de LLM ativo** (`api.anthropic.com`, `generativelanguage.googleapis.com`, `integrate.api.nvidia.com` ou o `base_url` do NIM, `openrouter.ai`), `news.google.com`, `api.gdeltproject.org` (e `api.tavily.com` se habilitado) e o portal DATASUS (+ S3 `s3.sa-east-1.amazonaws.com`) (só o job `ingest`); documentar e, no Compose, separar redes (`frontend`, `data`, `telemetry`).
- PDF: WeasyPrint com *URL fetcher* que bloqueia qualquer recurso remoto/`file://` fora do diretório de templates (anti-SSRF/LFI).
- OpenRouter e NIM repassam o prompt a terceiros/modelos de terceiros: como os prompts só contêm agregados públicos e notícias públicas, o risco é aceito; documentar no README e **nunca** adicionar dado não público ao prompt sem *Ask first*.

## 5. Testes de guardrail (obrigatórios)

Corpus em `tests/guardrails/` (tabela caso → veredito esperado): ≥ 15 injeções em notícias (PT/EN, Unicode oculto, markup), ≥ 10 narrativas com número inventado/arredondado indevido/URL falsa, ≥ 10 amostras de PII (CPF com/sem máscara, e-mail, telefone), parâmetros inválidos (UF, datas, janelas, campos extras, payloads tipo `BR'; REMOVE …` provando que nada é interpolado), usuário `api_ro` tentando escrever em `data`/`audit` (deve falhar), estouro de orçamento, e **teste de regressão "fail-closed"** (LLM fake que sempre mente ⇒ relatório degradado sem texto da narrativa).
