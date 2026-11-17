# ADR 0020 — Controles de perímetro da API (autenticação, limites, cabeçalhos)

- Status: aceito e implementado (2026-11-17) · Spec: [09 §3](../specs/09-agent-and-api-security.md)

## Contexto
A [spec 04](../specs/04-guardrails-security.md) prometia rate limit, limite de corpo e cabeçalhos de segurança, mas a API não tem nenhum middleware, chave ou limite (`api/app.py`). Cada `POST /v1/reports` pode acionar chamadas pagas a modelos e a rota de auditoria devolve a trilha a qualquer cliente. Hoje o risco é contido só porque o Compose publica a porta em `127.0.0.1`.

## Decisão
1. **Chave de API por cabeçalho** (`Authorization: Bearer`), chaves em `SRAG_API_KEYS` como `SecretStr`, comparação com `hmac.compare_digest`. Sem chave configurada, a API só sobe em `environment=dev`.
2. **Limites no processo:** taxa por chave, teto de gerações simultâneas e corpo ≤ 1 KiB, todos com 429/413/415 em RFC 9457 sem eco da entrada.
3. **Cabeçalhos de segurança** em middleware único; CSP restritiva na resposta HTML.
4. **Auditoria da API:** recusas viram evento e contador sem a chave.
5. Implementação como middleware/dependências FastAPI pequenos, injetáveis e testáveis com relógio falso.

## Alternativas
| Opção | Avaliação |
|---|---|
| Só proxy reverso (nginx/Traefik) na frente | necessário para TLS, mas não conhece custo de LLM nem chaves por cliente; mantido como complemento |
| OAuth2/OIDC | adequado a produção multiusuário; excessivo para uma PoC sem usuários finais; trocável depois, a dependência de auth é um ponto único |
| mTLS | forte, mas operacionalmente pesado para a PoC |
| Rate limit distribuído (Redis) | só faz sentido com várias réplicas; o processo único basta e é documentado como limite |

## Consequências
O limite em memória não é compartilhado entre réplicas (documentar). Chaves estáticas exigem rotação manual. Em troca, o custo por abuso fica limitado e a trilha deixa de ser pública na rede.
