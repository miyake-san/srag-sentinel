# ADR 0013 — Achados do spike do SurrealDB (T0c)

- Status: aceito (2026-11-16) · Scripts: `spikes/t0c/` (`surreal_spike.py`, `surreal_spike2.py`, `surreal_spike3.py`, `compose.spike.yaml`) · Servidor `surrealdb/surrealdb:v4.0.1` + SDK Python `surrealdb` 3.0.0, Python 3.14

## Compatibilidade
SDK 3.0.0 (cliente puro Python) conecta por WebSocket ao servidor v4.0.1 e executa tudo que a spec precisa. API usada: `AsyncSurreal(url)` (fábrica), `await db.signin({...})`, `await db.use(ns, db)`, `await db.query(sql, vars)` → objeto com `.execute()` (lista de resultados por statement), `await db.close()`.

## Resultados (✔ = confirmado)
- ✔ **Upsert idempotente** com id de registro em array: `UPSERT srag_daily:[$uf, $day] SET …` (2 execuções → 3 registros); índice `UNIQUE (uf, day)`.
- ✔ **Agregação parametrizada**: `SELECT math::sum(cases) AS cases … WHERE day >= $start AND day <= $end AND ($uf = 'BR' OR uf = $uf) GROUP ALL` retorna os totais corretos para `BR` e para uma UF.
- ✔ **Injeção inerte**: parâmetro `"BR'; REMOVE TABLE srag_daily; --"` não executa nada (tabela intacta).
- ✔ **Usuário `VIEWER` (api_ro)**: lê; CREATE/UPDATE/DELETE **não alteram dados**, mas **não levantam exceção — retornam resultado vazio** (`[[]]`). ⇒ testes e código devem verificar estado/resultado, não depender de exceção.
- ✔ **Auditoria append-only via record access**: `DEFINE ACCESS audit_writer ON DATABASE TYPE RECORD SIGNIN (… crypto::argon2::compare …)` + `signin({"namespace","database","access","variables"})` funciona; o writer faz CREATE e SELECT; **UPDATE e DELETE são bloqueados** (`PERMISSIONS FOR update, delete NONE`; dados intactos); `UNIQUE(seq)` rejeita duplicata com `ValidationError`; tabela de credenciais `svc` com `PERMISSIONS NONE` não é legível pelo writer.
- ✔ **`READONLY` em campos** é imposto **inclusive a usuário de sistema EDITOR** (tentativa de alterar `hash` falhou).

## Correção ao desenho original (achado importante)
- ⚠️ Com `PERMISSIONS FOR create FULL`, um usuário de sistema **VIEWER conseguiu CREATE** em `audit_event` (as permissões de tabela se aplicam ao VIEWER e `FULL` as concede). **Correção validada:** `FOR create WHERE $access = 'audit_writer'` (+ `FOR update, delete NONE`) → writer cria, **reader VIEWER não cria**.
- ⚠️ Usuário de sistema **EDITOR consegue DELETE** de registros mesmo com `delete NONE` (bypass confirmado), e root também. Logo **a aplicação nunca recebe credenciais EDITOR/OWNER para o banco `audit`**: só o record-access `audit_writer` (escrita) e um `VIEWER` (leitura). O que EDITOR/root podem fazer é detectado por hash chain + `audit verify` + exportação JSONL externa (defesa em profundidade, já prevista).

## Decisões
1. Esquema da auditoria: tabela `SCHEMAFULL` com campos `READONLY`, índice `UNIQUE(seq)`, `PERMISSIONS FOR select FULL FOR create WHERE $access = 'audit_writer' FOR update, delete NONE`; acesso `audit_writer` (record) para escrita; `audit_reader` (`VIEWER`) para leitura; credenciais de EDITOR/OWNER só em bootstrap/administração (fora da app).
2. Banco `data`: `ingest` (EDITOR, apenas no job), `api_ro` (VIEWER). Tabelas sem `PERMISSIONS` explícitas (padrão restritivo) — escrita do VIEWER confirmada como inócua.
3. O adaptador **verifica o resultado** de cada escrita (registro retornado não vazio; senão erro) — essencial para a auditoria, onde uma negação silenciosa deve **abortar a execução**.
4. Testes de integração assertam **estado final** (via root) e não exceções para negações de permissão.
5. `$session.*`/`$auth` retornaram `None` nas sessões de teste: não usar para lógica; basear permissões em `$access`.

## Pendências para a T3/T9
- Rodar `db init` real (ns/db explícitos: o spike usou root com `use` direto) e testar persistência (`rocksdb`/`surrealkv`) e healthcheck `surreal isready`.
- Medir desempenho de consulta dos agregados com ~20 mil registros (esperado trivial).
