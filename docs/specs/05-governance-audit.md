# 05 — Governança, Auditoria e Transparência

Parte de [SPEC.md](../../SPEC.md).

Objetivo: para qualquer relatório, permitir responder **"o que o agente fez, com quais entradas, por quê, e dá para confiar neste registro?"** sem depender de memória ou de logs voláteis.

## 1. Telemetria ≠ auditoria

| | OTel (06) | Trilha de auditoria (este doc) |
|---|---|---|
| Propósito | operar/depurar | prestar contas/investigar |
| Retenção | curta, amostrável | longa, sem amostragem |
| Integridade | não garantida | **tamper-evident** (hash chain) |
| Conteúdo | latência, erros, atributos | decisões, entradas/saídas por hash, vereditos |

## 2. Registro de eventos

Tabela `audit_event` no **banco `audit` do SurrealDB** (namespace `srag`), **append-only**, um registro por evento; exportação periódica para `audit/audit-YYYYMMDD.jsonl` (`srag-sentinel audit export`) para arquivamento/WORM. Esquema (`AuditEvent`, versionado; mostrado em JSON):

```json
{
  "schema": "audit.v1",
  "seq": 17,
  "ts": "2026-11-16T14:03:22.114Z",
  "run_id": "…uuidv7…",
  "trace_id": "…",
  "actor": "agent|tool|guardrail|system|user",
  "node": "synthesize",
  "event": "llm_call|tool_call|guardrail_verdict|decision|degradation|router_decision|judge_verdict|task_exhausted|kg_write|kg_quarantine|run_start|run_end",
  "inputs_hash": "sha256:…",
  "outputs_hash": "sha256:…",
  "details": { "model": "…", "prompt_id": "synthesize@3", "prompt_sha256": "…",
               "tokens_in": 1840, "tokens_out": 412, "rule_id": "G3.numeric_grounding",
               "action": "block", "reason": "number 12,4% not in metrics" },
  "prev_hash": "sha256:…",
  "hash": "sha256:…"
}
```

- `hash = sha256(canonical_json(evento sem 'hash') )`, incluindo `prev_hash` ⇒ **uma cadeia global** no banco `audit` (`seq` monotônico, `DEFINE INDEX … UNIQUE` em `seq` impede bifurcação); o exportador JSONL repete a cadeia e referencia o hash do arquivo anterior.
- **Append-only em camadas (defesa em profundidade) — validado no spike T0c ([ADR 0013](../adr/0013-surrealdb-findings.md)):** (1) a app escreve como **record access `audit_writer`**, com `PERMISSIONS FOR select FULL FOR create WHERE $access = 'audit_writer' FOR update, delete NONE` (UPDATE/DELETE bloqueados; `VIEWER` não consegue criar; a tabela de credenciais do writer tem `PERMISSIONS NONE`); (2) campos `READONLY` (impostos inclusive a EDITOR) e `UNIQUE(seq)`; (3) cadeia de hash + `audit verify`; (4) exportação JSONL fora do banco. **Limite assumido:** usuários de sistema EDITOR/OWNER e root *conseguem* apagar registros — por isso a app **nunca** recebe essas credenciais e qualquer remoção por administradores é detectada por (3)/(4).
- Negações de permissão no SurrealDB **não levantam exceção** (retornam resultado vazio): o adaptador exige o registro criado na resposta; resposta vazia ⇒ erro ⇒ a execução aborta.
- Escrita serializada (transação por evento; único escritor por processo, `seq` reservado de forma atômica); falha ao auditar **aborta a execução** (sem auditoria não há relatório).

## 3. O que é registrado (cobertura mínima por execução)

1. `run_start`: parâmetros validados, versão do código (git sha), versão do schema, `data_snapshot_sha256` e `manifest` de ingestão, **provedor/modelo de LLM** configurados.
2. Cada **chamada de tool**: nome, args (JSON canônico), `outputs_hash`, duração, status.
3. Cada **chamada de LLM**: provedor/modelo/versão, `prompt_id@version` + hash, parâmetros (temperatura 0), tokens, `inputs_hash`/`outputs_hash`; conteúdo só com `AUDIT_STORE_CONTENT=true`.
4. Cada **veredito de guardrail**: camada, `rule_id`, ação, motivo (sem dado sensível).
4a. Cada **decisão do router** (`router_decision`: tarefa, tier, tentativa, motivo de escalada), **veredito do juiz** (`judge_verdict`: rubrica@versão, nota, aprovado, issues), **tarefa esgotada** (`task_exhausted`: política aplicada) e **escrita/quarentena no grafo** (`kg_write`, `kg_quarantine`: ids, tipo, motivo; sem texto) — [07](07-graphrag-knowledge-graph.md), [08](08-llm-router-judge.md).
5. Cada **decisão do agente** (registro de decisão explícito, `event="decision"`): ex. queries de notícia escolhidas e justificativa curta estruturada, artigos aceitos/rejeitados (id, domínio, motivo), retry de narrativa, degradações.
6. `run_end`: hash do `report.json` e do HTML, estado (`ok|degraded|failed`), `degradations`.

## 4. Transparência para o usuário do relatório

- O relatório mostra: modelo e versão do prompt usados, fontes de notícia com links, `as_of`, hash do snapshot de dados (`data_snapshot_sha256`), selo de **proxy**, avisos de maturidade, lista de degradações e o `run_id` para consulta da auditoria.
- `GET /v1/audit/{run_id}` devolve os eventos da execução (sem conteúdo sensível).
- Todo texto gerado pelo LLM é marcado como tal ("Texto gerado por IA a partir dos dados abaixo; verifique as fontes").

## 5. Verificação e reprodutibilidade

- `srag-sentinel audit verify [--run-id …] [--file …]`: recalcula a cadeia no banco (ou num JSONL exportado); reporta primeiro registro inválido/lacuna de `seq`. Código de saída ≠ 0 se houver adulteração. Coberto por teste (editar uma linha ⇒ detecta).
- **Reprodutibilidade:** com `data_snapshot_sha256`, `as_of`, versão do código e prompts, as **métricas são reproduzíveis bit a bit**; a narrativa é reproduzível via *replay*: modo de teste que reusa respostas gravadas do LLM/notícias (fixtures) identificadas por `inputs_hash`.

## 6. Governança do projeto

- **ADRs** em `docs/adr/` para cada decisão da tabela de [01](01-architecture.md) §4 (formato curto: contexto, decisão, consequências, alternativas).
- **Prompts versionados** com changelog; mudança de prompt = PR com casos de teste do corpus de grounding.
- **Model card / limitações** no README: o que o sistema faz e não faz, métricas proxy, vieses de dado (atraso e sub-notificação), uso pretendido (apoio à vigilância).
- **Papéis e acesso (evolução documentada):** leitura do relatório vs. leitura da auditoria vs. administração; na PoC, token de API simples.
- **Retenção:** auditoria 12 meses (configurável); relatórios por 90 dias; traces 7 dias.

## 7. Aceitação

- [ ] Toda execução de teste e2e produz cadeia válida cobrindo os itens 1–6 de §3.
- [ ] Adulteração (editar, remover ou reordenar registro) é detectada por `audit verify`; a credencial usada pela API não consegue `UPDATE`/`DELETE` em `audit_event` (teste de integração).
- [ ] Nenhum evento contém PII ou conteúdo bruto por padrão (teste automatizado sobre o arquivo).
- [ ] O relatório HTML expõe `run_id`, modelo, prompts, proveniência e degradações.
