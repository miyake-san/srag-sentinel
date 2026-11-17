# 09 — Segurança da superfície de agentes, API e (futuro) chat

Parte de [SPEC.md](../../SPEC.md). Complementa a [04](04-guardrails-security.md), que cobre G1–G4 e o tratamento de dados. Esta spec cobre o que a 04 prometia sem implementar (perímetro da API), registra os endurecimentos pedidos pela [validação](../security-validation.md) e fixa as condições para qualquer interface conversacional. Decisões: [ADR 0020](../adr/0020-api-perimeter-controls.md), [0021](../adr/0021-conversational-surface-policy.md), [0022](../adr/0022-injection-detection-is-a-signal.md).

## 1. Superfícies

| Superfície | Quem fala com ela | Estado |
|---|---|---|
| API HTTP (`POST /v1/reports`, `GET /v1/reports/{id}`, `GET /v1/audit/{id}`) | qualquer cliente de rede | implementada, **sem autenticação nem limites** (ver §3) |
| CLI | operador local | implementada; confiança = acesso ao host |
| Chamadas a LLM (planejar consultas, extrair afirmações, juiz, resumir, sintetizar) | só o código | implementada; modelos sem ferramentas ([ADR 0004](../adr/0004-llms-without-tools-untrusted-data.md)) |
| Notícias e evidências do grafo | provedores externos | implementada; dado não confiável (G2) |
| **Chat / pergunta livre ao agente** | usuário final | **não existe**; só pode ser criado sob §5 |

## 2. Modelo de ameaças da superfície (adições à 04 §1)

| Ameaça | Controle exigido |
|---|---|
| Abuso de custo: cada `POST /v1/reports` pode disparar até 3 chamadas ao modelo grande e dezenas ao pequeno | A1–A4 |
| Leitura da trilha de auditoria por quem não deveria (`/v1/audit`) | A1, A6 |
| Navegador interpretando artefato como outro tipo ou embutindo em frame | A5 |
| Detector de injeção contornado (homóglifos, outros idiomas, ofuscação) | [ADR 0022](../adr/0022-injection-detection-is-a-signal.md): defesa em camadas, não regex única |
| Afirmação qualitativa falsa mas "citada" passa no G3 (que confere números e referências, não fidelidade semântica) | juiz de fidelidade + quarentena (spec 07/08); risco residual declarado |
| Dado pessoal fora dos padrões validáveis (nome, RG, CEP, cartão) | §4 |

## 3. Perímetro da API (requisitos)

| ID | Requisito | Verificação |
|---|---|---|
| A1 | Toda rota exceto `/healthz` e `/readyz` exige `Authorization: Bearer <chave>`; chaves em `SRAG_API_KEYS` (`SecretStr`), comparação em tempo constante; sem chave configurada a API **recusa subir** fora de `environment=dev`; falha = 401 com RFC 9457 e sem eco | teste de rota sem/com chave errada/certa |
| A2 | Limite de taxa por chave (padrão 10 req/min em `POST /v1/reports`) → 429 com `Retry-After` | teste com relógio injetado |
| A3 | Teto de gerações simultâneas (padrão 2); excedente → 429, nunca fila ilimitada | teste com serviço lento |
| A4 | Corpo ≤ 1 KiB e `Content-Type: application/json` obrigatório → 413/415 | teste |
| A5 | Cabeçalhos: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` em todas as respostas; `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'` no HTML do relatório; `Content-Disposition` no PDF | teste de cabeçalhos |
| A6 | `/v1/audit/{id}` exige a mesma chave e devolve só `seq, ts, node, event, hash` e contadores; `details` nunca inclui texto livre | teste |
| A7 | Cada recusa de A1–A4 vira evento de auditoria/contador OTel (`srag.api.rejections{reason}`) sem registrar a chave | teste |
| A8 | Em Compose "prod-like", a API só publica em `127.0.0.1` ou atrás de proxy TLS (já é o caso: `127.0.0.1:8080`) | revisão do `compose.yaml` |

## 4. Endurecimento de detecção e PII

- **Normalização antes de detectar (ADR 0022):** NFKC, remoção de formato/controle (já feita), dobra de homóglifos comuns (cirílico/grego → latino), colapso de espaços entre letras isoladas, e checagem também no texto sem espaços/pontuação. Idiomas cobertos: PT, EN, ES; FR e outros ficam para a defesa estrutural.
- **Regra de ouro:** o detector reduz ruído; **a barreira é estrutural** (sem ferramentas, saída tipada, G3, escape, quarentena). Nenhum requisito de segurança pode depender dele sozinho.
- **PII:** acrescentar RG com dígito verificador do estado quando houver padrão, CEP, cartão (Luhn) e nomes precedidos de pistas (`paciente`, `sr.`, `sra.`, `internado`). Nome sem pista continua fora do alcance e é um risco aceito e documentado (só texto público de veículos entra no prompt).

## 5. Interface conversacional (condições para existir)

Não há chat. Se for criado (ADR 0021), todos os itens são pré-requisito:

| ID | Requisito |
|---|---|
| C1 | **G1b:** texto do usuário é dado não confiável: limite de tamanho, normalização (§4), detector de injeção como sinal, PII scrub **antes** de chegar ao modelo e antes de qualquer log |
| C2 | O modelo do chat **não tem ferramentas livres**: só um conjunto fixo e somente-leitura (`get_metrics(uf, as_of, window)`, `get_report(run_id)`) com argumentos validados pelo G1; nada de SurrealQL, URL ou arquivo vindo do modelo |
| C3 | Respostas passam pelo **G3** (números das métricas/evidências, referências existentes, política de conteúdo) e recusam diagnóstico/conduta clínica; falha fecha |
| C4 | Escopo fechado: perguntas fora de vigilância de SRAG recebem recusa padrão, sem chamada ao modelo grande |
| C5 | Sessões isoladas por chave; histórico com teto de turnos e tamanho; **sem memória entre sessões**; histórico armazenado só como hash + versão na auditoria |
| C6 | Os limites A1–A4 valem por sessão, mais teto de tokens por turno e por sessão (G4 estendido) |
| C7 | Conteúdo recuperado (notícias, evidências) continua delimitado e escapado; instruções do usuário e dados nunca compartilham o mesmo bloco |
| C8 | Corpus adversarial de chat (≥ 30 casos: injeção direta, extração de prompt/segredos, pedido de diagnóstico, troca de persona, multi-turno) em `tests/guardrails/` e execução contra modelo real antes de liberar |

## 6. Testes obrigatórios (novos)

`tests/unit/api/test_perimeter.py` (A1–A7), `tests/guardrails/test_detector_normalisation.py` (homóglifos, ES, espaçamento, base64 **não** detectado e documentado), `tests/guardrails/test_pii.py` (RG, CEP, cartão, nome com pista). Quando C1–C8 forem implementados: `tests/guardrails/chat/`.

## 7. Estado

| Item | Estado em 2026-11-17 |
|---|---|
| A1–A7 | **implementados** em [`api/perimeter.py`](../../src/srag_sentinel/api/perimeter.py), testados em `tests/unit/api/test_perimeter.py` (ADR 0020). Limites: contadores em memória (um processo); respostas 500 do `ServerErrorMiddleware` ficam fora do middleware e não recebem os cabeçalhos de A5 |
| A8 | atendido |
| §4 detecção/PII | não implementado |
| C1–C8 | não aplicável (não há chat) |
