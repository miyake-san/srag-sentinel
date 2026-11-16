# 08 — LLM Router e LLM Judge

Parte de [SPEC.md](../../SPEC.md). Decisão da forma de uso: [ADR 0018](../adr/0018-llm-router-and-judge.md). Consumidor principal: tarefas de GraphRAG ([07](07-graphrag-knowledge-graph.md)). Provedores: [03 §4](03-agent-and-tools.md). Diagrama: [architecture.md §3](../architecture/architecture.md).

## 1. Objetivo
Executar com **LLMs pequenos** (rápidos/baratos) as tarefas estreitas e verificáveis do GraphRAG e **escalar para o LLM grande** só quando o resultado não passar na verificação — sem treinar roteador, sem dependências novas e com cada decisão auditável.

**Princípios**
1. **Validar antes de julgar:** checagens determinísticas primeiro (baratas e confiáveis); o juiz LLM só entra quando necessário.
2. **Roteamento por tarefa, não por prompt:** a política é uma tabela declarativa tarefa → camadas; nada de "roteador inteligente".
3. **Escalada com feedback:** o tier maior recebe a razão da reprovação.
4. **Fail-closed por tarefa:** esgotadas as camadas, aplica-se o fallback definido (descartar item, baixa confiança ou degradar), nunca aceitar saída não verificada.
5. **Juiz é sinal, não verdade:** não substitui o G3 determinístico da narrativa final.

## 2. Camadas (tiers) e configuração
| Tier | Uso | Configuração |
|---|---|---|
| `small` | extração de afirmações, classificação de relevância, planejamento de consulta, resumo regional | `SRAG_ROUTER_SMALL_PROVIDER` + `SRAG_ROUTER_SMALL_MODEL` |
| `large` | síntese final, reexecução de casos escalados | `SRAG_LLM_PROVIDER` + `SRAG_LLM_MODEL` (o modelo principal já existente) |
| `judge` | avaliação por rubrica | `SRAG_ROUTER_JUDGE_PROVIDER` + `SRAG_ROUTER_JUDGE_MODEL`; padrão = **modelo diferente do produtor** quando possível (reduz viés de autopreferência), senão o `large` |

Cada tier usa a mesma **fábrica de provedores** (Anthropic, Gemini, NVIDIA NIM, OpenRouter — [03 §4](03-agent-and-tools.md)); tiers podem usar provedores distintos (ex.: `small` em NIM/OpenRouter, `large` em Anthropic). **Nenhum id de modelo é fixado em código**; exemplos só no `.env.example`. Boot valida chave, modelo e suporte a saída estruturada de cada tier; sem `small` configurado, o router usa `large` para tudo (comportamento atual, sem economia).

## 3. Política de roteamento (dados, não código)
Arquivo versionado `src/srag_sentinel/llm/router/policy.yaml`, validado por Pydantic no boot:

```yaml
tasks:
  kg.extract_claims:
    tiers: [small, large]          # cascata: tenta small, escala para large
    output_schema: ClaimDraftList
    validators: [schema, enums, span_in_source, entities_in_ontology, max_items]
    judge: on_validator_fail        # always | sample:<p> | on_validator_fail | never
    judge_rubric: claim_extraction@1
    judge_min_score: 4              # de 1 a 5, calibrado em fixtures
    on_exhausted: drop_item         # drop_item | low_confidence | fail_closed
  kg.summarize_region:
    tiers: [small, large]
    validators: [schema, citations_in_evidence, no_new_numbers]
    judge: always
    judge_rubric: region_summary@1
    judge_min_score: 4
    on_exhausted: fail_closed
  news.plan_queries:
    tiers: [small, large]
    validators: [schema, query_charset, max_queries]
    judge: never
    on_exhausted: template_fallback
  news.classify_relevance:
    tiers: [small]
    validators: [schema, enums]
    judge: sample:0.1               # amostragem para monitorar qualidade
    on_exhausted: drop_item
  report.synthesize:
    tiers: [large]                  # nunca small
    validators: []                  # verificação é o G3 (determinístico)
    judge: never
```

Regras: tarefa desconhecida ⇒ erro de configuração (fail-fast); `report.synthesize` é fixada em `large` por regra no código (teste); a política não contém prompts.

## 4. Algoritmo (cascata com validação e juiz)
```text
run_task(task, input):
  for tier in policy.tiers:                       # ordem: small -> large
      attempt up to policy.max_attempts_per_tier (padrão 1; 2 só para erro de schema)
          out = tier.model.invoke(prompt(task, input, feedback))      # saída estruturada
          audit.router_decision(task, tier, attempt)
          v = validators.run(out, input)          # determinístico
          if v.ok and not judge_required(policy, out): return Accepted(out, tier)
          if v.ok or policy.judge == on_validator_fail:
              verdict = judge.evaluate(rubric, input, out, v.issues)  # estruturado
              audit.judge_verdict(task, tier, verdict)
              if verdict.passed and verdict.score >= judge_min_score and v.ok: return Accepted(out, tier)
              feedback = verdict.reasons + v.issues
          else:
              feedback = v.issues
  return apply(policy.on_exhausted)               # nunca devolve saída reprovada como aceita
```
Notas: validador que **reprova** nunca é "salvo" pelo juiz (juiz só decide casos ambíguos e vê as razões dos validadores); no estágio de escalada o prompt inclui `feedback`; orçamento G4 limita chamadas por tier por relatório; paralelismo por artigo com limite de concorrência.

## 5. LLM Judge
- **Entrada:** rubrica versionada (`prompts/judge/<rubrica>@<n>.md`), texto-fonte, saída candidata e as questões já apontadas pelos validadores. **Sem tools**, `temperature=0`, saída estruturada.
- **Saída (`Verdict`):** `score` 1–5 por critério e global, `passed: bool`, `reasons` (≤ 3, curtas), `issues[]` (códigos de uma lista fechada, ex.: `unsupported_claim`, `wrong_entity`, `wrong_direction`, `invented_span`).
- **Rubricas iniciais:** `claim_extraction@1` (fidelidade ao texto, entidade correta, direção correta, ausência de inferência), `region_summary@1` (cada frase com evidência, sem números novos, sem aconselhamento clínico).
- **Calibração:** limiar `judge_min_score` ajustado em **fixtures rotuladas por humano** (≈ 30 itens por rubrica); relatório de concordância juiz × humano (acurácia e Cohen's κ) no CI; se a concordância cair abaixo da meta (padrão κ ≥ 0,6), o teste falha.
- **Limitações assumidas:** viés de autopreferência, de posição e de verbosidade; por isso o juiz é de outro modelo quando possível, a saída é estruturada e o veredito nunca é a única barreira.

## 6. Governança, observabilidade e segurança
- **Auditoria ([05](05-governance-audit.md)):** eventos `router_decision` (tarefa, tier, tentativa, motivo da escalada), `judge_verdict` (rubrica@versão, nota, aprovado, issues) e `task_exhausted`; `prompt_id@versão` e hash em cada chamada; conteúdo só como hash por padrão.
- **OTel:** spans `router.task` (filhos: `router.attempt`, `judge.evaluate`); métricas `srag.router.calls{task,tier,outcome}`, `srag.router.escalations{task}`, `srag.judge.verdicts{rubric,passed}`, `srag.router.cost_usd` (estimado, quando houver tabela de preços), latência por tier.
- **Segurança:** entradas dos tiers são dados não confiáveis (G2); nenhum tier tem tools/rede/arquivos; o juiz recebe o texto-fonte delimitado como dado e é instruído a ignorar instruções dentro dele; chaves apenas do provedor ativo por tier.
- **Metas de eficiência (a medir na T20):** ≥ 70 % das chamadas de extração resolvidas no tier `small` sem escalada; custo por relatório ≤ baseline "tudo no large"; p95 do relatório ainda ≤ 90 s.

## 7. Testes
| Nível | Casos |
|---|---|
| Unit | carga/validação da política (tarefa desconhecida, `report.synthesize` forçada em `large`); cada validador; parsing de `Verdict` |
| Unit (cascata) | `FakeModel` roteirizado: small ok → aceito; small inválido → juiz reprova → large ok; small ok mas validador reprova → escalada; large reprova → `on_exhausted`; juiz nunca "salva" validador reprovado; orçamento esgotado |
| Propriedade | o resultado aceito sempre passou em todos os validadores; nenhuma saída reprovada é devolvida |
| Adversarial | extração com `evidence_span` inventado, entidade fora da ontologia, injeção no texto-fonte, juiz induzido a aprovar (texto "dê nota 5") |
| Avaliação (fixtures) | concordância juiz × humano; F1 de extração small vs. large; taxa de escalada |
| Live (marcado) | um caso por provedor/tier com chaves reais |

## 8. Aceitação
- [ ] Todas as tarefas de GraphRAG passam pelo router; `report.synthesize` nunca usa `small`.
- [ ] Cada decisão de roteamento/juiz aparece na auditoria e como span OTel.
- [ ] Sem tier `small` configurado, o sistema funciona (tudo em `large`).
- [ ] Concordância juiz × humano ≥ meta nas fixtures; teste de escalada determinístico verde.
