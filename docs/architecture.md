# Architecture

Two paths (ingest and triage), two surfaces (the deterministic pipeline and `explain`), one boundary between
statistics and judgement. **Blue = deterministic Python. Orange = LLM call. Red = the gate, the only place a
judgement becomes a write.**

```mermaid
flowchart TB
    classDef code fill:#e8eef7,stroke:#33507a,color:#10203a
    classDef llm fill:#fdf0e3,stroke:#b3651a,stroke-width:2px,color:#5a3208
    classDef gate fill:#f7e9ee,stroke:#a32d4e,stroke-width:2px,color:#4a0f21
    classDef store fill:#fff,stroke:#5c6370,stroke-dasharray:4 3,color:#2a2f37
    classDef out fill:#e9f4ec,stroke:#2f6b42,color:#12301d

    subgraph I["1 · INGEST — when CI runs"]
        direction LR
        GH["GitHub Actions API<br/>runs · jobs · artifacts"]:::code --> PARSE["parse JUnit XML<br/>pass/fail per matrix cell"]:::code
    end

    DB[("SQLite · observations · rosters · decision ledger")]:::store
    PARSE --> DB

    subgraph T["2 · TRIAGE — scheduled sweep"]
        direction TB
        STATS["stats.py<br/>p̂ · Wilson 95% · n measured/inferred<br/>cells failed/present · dispersion · onset"]:::code
        PRE{{"cheap checks<br/>overridden · triaged today<br/>n &lt; min_runs · budget spent"}}:::gate
        CLS("classifier<br/>verdict · confidence<br/>conflicting signals"):::llm
        COR("correlation<br/>regression only"):::llm
        GATE{{"ACTION GATE<br/>confidence ≥ threshold?<br/>already quarantined?"}}:::gate
        DRAFT("drafter<br/>prose only"):::llm
        ART["artifact assembled in code<br/>evidence pasted verbatim"]:::code
        STATS --> PRE
        PRE -->|worth a verdict| CLS
        CLS --> GATE
        CLS -->|regression| COR --> GATE
        GATE -->|act| DRAFT --> ART
    end

    DB --> STATS
    PRE -.->|no model call| SKIP
    GATE -->|blocked| SKIP["review queue · deferred · none"]:::out

    subgraph A["3 · ACT — scratch branch only, never merged"]
        direction LR
        ISSUE["issue<br/>idempotent by title"]:::out
        QPR["quarantine PR<br/>xfail, not skip"]:::out
        UNQ["un-quarantine PR<br/>after N clean runs"]:::out
    end
    ART --> ISSUE & QPR
    DB -.->|quarantined test recovers| UNQ
    ISSUE & QPR & UNQ & SKIP -.->|outcome| DB

    subgraph X["4 · EXPLAIN — interactive, read-only by construction"]
        direction LR
        AGENT("orchestrator agent<br/>sequences the tools itself"):::llm
        TOOLS["read-only tools<br/>health · commit · classify · correlate"]:::code
        AGENT <--> TOOLS
    end
    DB --> TOOLS
    X -. "no path to ACT" .-> A
```

Every orange box sits inside a blue path: a model never touches the API, the database, or the decision to write.
The first gate disposes of cases before any model is called; the second decides whether a verdict becomes an
artifact. `explain` shares the tools and has no path to `ACT` at all.
