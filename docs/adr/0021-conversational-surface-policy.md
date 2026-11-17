# ADR 0021 — Não há interface de chat; condições para criar uma

- Status: aceito (2026-11-17) · Spec: [09 §5](../specs/09-agent-and-api-security.md)

## Contexto
O sistema gera relatórios a partir de parâmetros tipados; nenhum texto livre do usuário chega a um modelo (spec 04, G1). Um chat mudaria o perfil de risco: injeção **direta**, extração de prompt e de segredos, troca de persona, ataques multi-turno, memória e escolha de ferramentas pelo modelo. Nada disso está coberto pelos guardrails atuais.

## Decisão
1. **A PoC não expõe chat nem pergunta livre.** Qualquer campo de texto livre que chegue a um modelo exige antes um novo ADR.
2. Se um chat for criado, valem os requisitos **C1–C8** da spec 09: texto do usuário como dado não confiável (G1b), conjunto fixo e somente-leitura de funções com argumentos validados, resposta verificada pelo G3, escopo fechado, sessões isoladas e sem memória entre elas, limites por sessão e corpus adversarial executado contra modelo real.
3. O modelo do chat **nunca** monta consultas, URLs ou caminhos; escolhe entre funções fixas e o código valida os argumentos.

## Alternativas
- **Liberar um chat simples já**: descartado; os guardrails G2/G3 foram desenhados para um fluxo fixo, não para diálogo.
- **Delegar a segurança ao prompt do sistema**: não é barreira ([ADR 0004](0004-llms-without-tools-untrusted-data.md)).

## Consequências
A superfície permanece pequena e a avaliação de segurança continua válida. Quem quiser conversar com o agente precisa pagar o custo de C1–C8, o que é intencional.
