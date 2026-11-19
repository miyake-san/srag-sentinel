# Arquitetura — SRAG Sentinel (diagramas Mermaid)

> Fonte de verdade dos diagramas (renderizam no GitHub). O PDF entregável (T19) é gerado a partir deste arquivo. Descrição textual em [`docs/specs/01-architecture.md`](../specs/01-architecture.md). Legenda: **G1–G4** = guardrails; **KG** = grafo de conhecimento; **tier small/large** = modelos pequenos/grandes do [LLM Router](../specs/08-llm-router-judge.md).

## 1. Visão geral (contexto e componentes)

```mermaid
flowchart LR
    user["Cliente<br/>CLI / HTTP"]

    subgraph app["Aplicação srag-sentinel (container app)"]
        direction TB
        api["API FastAPI<br/>G1 entrada · run_id · RFC 9457"]
        orch["Agente Orquestrador<br/>LangGraph StateGraph"]
        tools["Tools<br/>get_srag_metrics · get_srag_series<br/>search_news · search_knowledge_graph"]
        guard["Guardrails<br/>G2 notícias · G3 saída · G4 orçamento"]
        router["LLM Router + LLM Judge<br/>tarefas small → large (cascata)"]
        gov["Governança<br/>trilha de auditoria (hash chain)"]
        rep["Relatório<br/>HTML · JSON · PDF"]
    end

    subgraph db["SurrealDB (container)"]
        direction TB
        d_data[("db data<br/>agregados diários por UF")]
        d_kg[("db kg<br/>grafo de conhecimento<br/>nós · arestas · FTS · HNSW opcional")]
        d_audit[("db audit<br/>append-only")]
        d_app[("db app<br/>relatórios · cache")]
    end

    subgraph ext["Fontes e provedores externos"]
        direction TB
        datasus["Open DATASUS<br/>Parquet no S3"]
        gnews["Google News RSS pt-BR"]
        gdelt["GDELT DOC 2.0"]
        subgraph llms["Provedores de LLM"]
            anth["Anthropic (padrão)"]
            gem["Google Gemini"]
            nim["NVIDIA NIM"]
            orr["OpenRouter"]
        end
    end

    subgraph obs["Observabilidade (OpenTelemetry)"]
        direction TB
        col["OTel Collector"]
        jae["Jaeger"]
        prom["Prometheus"]
        graf["Grafana"]
        col --> jae
        col --> prom
        prom --> graf
        jae --> graf
    end

    ing["Job de ingestão<br/>Polars: só colunas permitidas"]

    user --> api --> orch
    orch --> tools
    orch --> guard
    orch --> router
    orch --> gov
    orch --> rep
    tools --> d_data
    tools --> d_kg
    tools --> gnews
    tools --> gdelt
    router --> anth
    router --> gem
    router --> nim
    router --> orr
    router --> d_kg
    gov --> d_audit
    rep --> d_app
    datasus --> ing --> d_data
    app -. "OTLP: traces · métricas · logs" .-> col
```

## 2. Fluxo do agente (LangGraph) com GraphRAG

```mermaid
flowchart TB
    subgraph linha1["Entrada, métricas e notícias"]
        direction LR
        start(["POST /v1/reports"]) --> n1["validate_request<br/>G1"]
        n1 --> n2["fetch_metrics<br/>tool → SurrealDB data"]
        n2 --> n3["plan_news_research<br/>LLM (tier small)"]
        n3 --> n4["collect_news<br/>tool → RSS / GDELT"]
        n4 --> g2{{"G2<br/>sanitiza · filtra · PII"}}
    end
    subgraph linha2["Grafo de conhecimento, síntese e verificação"]
        direction LR
        n5["build_kg<br/>extrai entidades e afirmações<br/>(router small + judge)"] --> n6["retrieve_context<br/>GraphRAG: FTS + travessia<br/>+ resumos regionais"]
        n6 --> n7["synthesize<br/>LLM (tier large)"]
        n7 --> g3{{"G3 verify_narrative<br/>números · evidências · política"}}
        g3 -- "violações (1 retry)" --> n7
        g3 -- "aprovado" --> n8["render_report<br/>HTML · JSON · PDF"]
        g3 -- "reprovado 2x" --> deg["relatório degradado<br/>só métricas e gráficos"]
        deg --> n8
        n8 --> n9["finalize<br/>sela a auditoria"]
        n9 --> fim(["relatório + run_id"])
    end
    linha1 --> linha2

    classDef llm fill:#e8f0fe,stroke:#4a6fd1;
    classDef guard fill:#fff4e5,stroke:#d98a00;
    class n3,n5,n7 llm;
    class g2,g3 guard;
```

## 3. LLM Router e LLM Judge (cascata)

```mermaid
sequenceDiagram
    autonumber
    participant N as Nó do grafo (ex.: build_kg)
    participant R as LLM Router
    participant S as Modelo small
    participant V as Validadores determinísticos
    participant J as LLM Judge
    participant L as Modelo large
    participant A as Auditoria / OTel

    N->>R: tarefa (id, entrada, schema)
    R->>A: router_decision (tarefa → tier small)
    R->>S: executa (saída estruturada)
    S-->>R: resultado
    R->>V: schema · enums · trecho existe no texto · entidade na ontologia
    alt validadores aprovam e política não exige juiz
        R-->>N: resultado aceito (tier small)
    else validadores reprovam ou política pede juiz
        R->>J: rubrica + fonte + resultado
        J-->>R: Verdict (nota, aprovado, motivos)
        R->>A: judge_verdict
        alt aprovado
            R-->>N: resultado aceito (tier small)
        else reprovado
            R->>L: reexecuta com o feedback do juiz
            L-->>R: resultado
            R->>V: revalida
            alt aprovado
                R-->>N: resultado aceito (tier large)
            else reprovado novamente
                R-->>N: fallback da tarefa (descartar item / baixa confiança / fail-closed)
            end
        end
    end
```

## 4. Modelo do grafo de conhecimento

```mermaid
erDiagram
    REGION ||--o{ UF : "in_region"
    UF }o--o{ UF : "adjacent_to"
    ARTICLE }o--|| SOURCE : "published_by"
    ARTICLE }o--o{ UF : "mentions"
    ARTICLE }o--o{ PATHOGEN : "about"
    ARTICLE ||--o{ CLAIM : "asserts"
    CLAIM }o--o{ UF : "concerns"
    CLAIM }o--o{ PATHOGEN : "concerns"
    UF ||--o{ SNAPSHOT : "has_snapshot"
    REPORT ||--o{ SNAPSHOT : "describes"
    REPORT }o--o{ ARTICLE : "cites"
    SUMMARY }o--|| REGION : "summarizes"

    UF {
        string code PK
        string name
    }
    PATHOGEN {
        string id PK
        string name_pt
        array aliases
    }
    ARTICLE {
        string id PK
        string title
        string url
        datetime published_at
        string sha256
    }
    CLAIM {
        string id PK
        string type
        string text
        string evidence_span
        float confidence
        string extractor
        string judge_verdict
        datetime expires_at
    }
    SNAPSHOT {
        string id PK
        date as_of
        string metrics_json
    }
```

## 5. Ingestão e dados

```mermaid
flowchart LR
    page["Página do recurso<br/>dadosabertos.saude.gov.br"] -- "link Baixar (regex restrita)" --> url["URL do Parquet no S3<br/>nome muda por semana"]
    url -- "scan_parquet + select<br/>só 7 colunas" --> pl["Polars"]
    pl --> clean["Limpeza<br/>null/inválido → ignorado<br/>datas inválidas descartadas"]
    clean --> agg["Agregação<br/>UF × dia → contadores"]
    agg --> merge["Merge entre arquivos anuais<br/>(mínimo 2 anos)"]
    merge --> up["UPSERT idempotente<br/>srag_daily"]
    merge --> man["Manifesto<br/>hash do snapshot"]
    up --> sdb[("SurrealDB · db data")]
    man --> sdb
```

## 6. Implantação (Docker Compose)

```mermaid
flowchart TB
    subgraph frontend["rede frontend"]
        cli(["Cliente"]) --> appc["app<br/>FastAPI + LangGraph"]
    end
    subgraph data["rede data (interna)"]
        appc --> sdb[("surrealdb<br/>volume persistente")]
        ingc["ingest<br/>(profile jobs)"] --> sdb
    end
    subgraph telemetry["rede telemetry"]
        appc -- "OTLP" --> otel["otel-collector"]
        ingc -- "OTLP" --> otel
        otel --> jaeger["jaeger"]
        otel --> prometheus["prometheus"]
        prometheus --> grafana["grafana"]
        jaeger --> grafana
    end
    appc -. "HTTPS" .-> net["Provedores de LLM · Google News · GDELT"]
    ingc -. "HTTPS" .-> dsus["Portal DATASUS / S3"]
```
