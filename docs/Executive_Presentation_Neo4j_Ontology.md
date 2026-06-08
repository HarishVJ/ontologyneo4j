# Executive Presentation: Unifi KPI Ontology with Neo4j
## Data-Driven Natural Language to SQL Chatbot Architecture

---

## Slide 1: Agenda & Executive Summary

**Goal**: Explain why we built a domain ontology on Neo4j to power a generic KPI chatbot that converts natural language questions into validated, auditable SQL.

**Key takeaway**: The ontology is not the database — it is the *brain* that teaches the chatbot what questions mean, which tables to use, and how to filter/group the data.

**Topics covered**:
1. Why Neo4j
2. Neo4j's role in our use case
3. What is an ontology (in our context)
4. Why we chose Neo4j for ontology storage
5. Alternative technologies evaluated
6. How the ontology is built on Neo4j
7. Scalability of the solution
8. Benefits of this design
9. Improvements over the current/previous design
10. Technical deep-dive: building & querying the ontology
11. Maintainability
12. What data lives in Neo4j
13. Visualizing the ontology
14. Application boot-time querying
15. Run-time query answering pipeline

---

## Slide 2: Why Neo4j? — The Graph Advantage

**The problem with traditional approaches**:
- Relational databases store KPI definitions as rows in tables with foreign keys.
- To answer "Which views join to which other views for this KPI?" you need 3-4 JOINs across metadata tables.
- Adding a new dimension (e.g., "group by city") requires schema migrations.

**Why a graph database (Neo4j) is the right fit**:

| Aspect | Relational (PostgreSQL) | Graph (Neo4j) |
|--------|----------------------|---------------|
| **Relationships** | Foreign-key JOINs at query time | Native pointers — traversals are O(1) per hop |
| **Schema flexibility** | ALTER TABLE for new entity types | Labels and properties added dynamically |
| **Query pattern** | `SELECT ... JOIN ... JOIN` | `MATCH (a)-[:REL]->(b)` — natural for connected data |
| **Introspection** | Hard to visualize table relationships | Built-in graph visualization (Browser / Bloom) |
| **Cognitive model** | Tables don't mirror human knowledge | Nodes & edges directly model "KPI uses View" |

**Bottom line for architects**: KPI metadata is inherently a graph — KPIs connect to views, views connect to columns, columns connect to term categories, terms connect to synonyms, views connect to each other via joins. A graph database models this without impedance mismatch.

---

## Slide 3: How Neo4j Helps Our Use Case

**Our use case**: A chatbot that receives questions like *"What is the attrition rate at MSP YTD?"* and must:
1. Recognize the KPI ("attrition rate")
2. Extract entities (station = MSP, period = YTD)
3. Find the correct view(s) and join path
4. Generate SQL with proper filters, grouping, and ordering

**Neo4j's specific contributions**:

1. **KPI Discovery** — `MATCH (k:KPI)-[:USES_VIEW]->(v)` retrieves everything needed to build a query plan.
2. **Term Resolution** — Term categories (stations, customers, divisions) and their terms are nodes. Fuzzy matching happens in Python, but the *authority* for what terms exist lives in the graph.
3. **Join Path Resolution** — `MATCH (a:View)-[j:JOINS_TO]->(b:View)` returns the exact `ON` condition, eliminating hardcoded SQL in the application.
4. **Rejection of Unsupported Filters** — Views declare `unsupported_term_categories`. The pipeline checks this at runtime by querying the graph.
5. **Governance & Versioning** — KPI nodes carry `version`, `status`, `owner`, and `valid_from`. Deprecated KPIs can be deactivated without code deploys.

---

## Slide 4: What Is an Ontology (In Our Context)?

**Analogy**: Think of the ontology as the "schema for the conversation."

**Components of our ontology**:

| Component | What it represents | Example |
|-----------|-------------------|---------|
| **KPI** | A business metric the user can ask about | `Attrition Rate`, `Employee Count` |
| **View** | A Snowflake view that holds the data | `AGGEMPCOUNT_ATTRITION_DATA_V_Table` |
| **TermCategory** | A dimension users filter by | `stations` (STATIONCODE), `customers` (CUSTOMERNAME) |
| **Term** | A specific value in a category | `MSP` (code), `Delta Air Lines` (canonical) |
| **Join** | How two views relate | `DIMHISTORYEMPLOYEE_V` joins to `FACTDAILYWORKDETAILS_MS_V` on EMPLOYEE_ID |
| **Filter** | A WHERE-clause template for a KPI | `column: STATIONCODE, source: detected_station` |
| **Step** | Ordered logic the LLM must follow | Step 1: apply filters; Step 2: compute rate |

**Key insight**: The ontology does not store *data* (no employee rows). It stores *meaning* — the rules that map human language to database queries.

---

## Slide 5: Why We Chose Neo4j for Ontology Storage

**Not because it's trendy. Because the problem is graph-shaped.**

1. **Native Relationship Traversal**
   - Query: *"Give me the KPI recipe, its steps, its filters, its views, and the joins between those views."*
   - In SQL: 5 JOINs across metadata tables.
   - In Cypher: Single `MATCH` with `OPTIONAL MATCH` — returned in ~2-5ms.

2. **Schema Evolution Without Migrations**
   - Adding `default_ranking_metric` to KPIs was a single `SET k.default_ranking_metric = ...` — no ALTER TABLE, no downtime.
   - New KPI families (employee_count, terminations, hours) were added by dropping new YAML files and running the loader.

3. **Human-Readable Queries**
   - `MATCH (k:KPI {name:'Attrition Rate'})-[:USES_VIEW]->(v)` reads like English.
   - Domain experts can inspect and validate the graph without SQL expertise.

4. **Built-in Visualization**
   - Neo4j Browser renders the ontology as an interactive graph — invaluable for debugging and stakeholder demos.

5. **Production-Ready**
   - Connection pooling, clustering (Enterprise), ACID transactions, and a mature Python driver (`neo4j` package).

---

## Slide 6: Alternative Options Evaluated

| Technology | Why considered | Why not chosen |
|------------|---------------|----------------|
| **PostgreSQL + JSONB** | Mature, team expertise | Metadata queries require 4-5 JOINs; visualization is poor; schema changes need migrations |
| **MongoDB** | Flexible schema | No native join support for cross-document relationships; graph traversals are client-side |
| **RDF / Triple Stores (Apache Jena)** | Academic "ontology" standard | Steeper learning curve; Cypher is more accessible for engineers; Neo4j ecosystem is richer |
| **In-Memory Python Dicts** | Fast, no DB dependency | Not shareable across services; changes require code deploys; no audit trail |
| **Snowflake Information Schema** | Already have Snowflake | Only stores physical schema, not business synonyms, KPI logic, or join semantics |

**Our choice**: Neo4j strikes the balance between **expressiveness** (native graph), **operational maturity** (clustering, monitoring), and **team accessibility** (Cypher is learnable in days).

---

## Slide 7: How the Ontology Is Built on Neo4j

**Source of truth**: Human-editable YAML files under `ontology/`

```
ontology/
  schema/
    terms.yaml           # Term categories + values
    views.yaml           # Snowflake view metadata
    joins.yaml           # Inter-view join definitions
    disambiguation.yaml  # Conflict resolution rules
  kpis/
    attrition.yaml       # KPI recipes
    contract_hierarchy.yaml
    employee_count.yaml
    terminations.yaml
    hours.yaml
  security/
    roles.yaml           # User authorization
```

**Build pipeline** (`ontology/loader.py`):

1. **Clear** existing graph (idempotent rebuild)
2. **Load Views** — `MERGE (v:View {name: $name})` with columns, aliases, date_column
3. **Load Joins** — `MATCH (a), (b) MERGE (a)-[j:JOINS_TO]->(b)`
4. **Load TermCategories** — `MERGE (tc:TermCategory {name: $name})` with match_type, threshold, groupable
5. **Load Terms** — `MERGE (t:Term {code:$code, category:$cat})` linked to their category
6. **Load KPIs** — `MERGE (k:KPI {id:$id})` linked to views, steps, filters
7. **Load Roles** — `MERGE (u:User {user_id:$uid})` with authorized stations

**Key design principle**: YAML is the *authoring* layer. Neo4j is the *runtime* layer. Changes go YAML → Loader → Neo4j. No manual Cypher editing required for domain changes.

---

## Slide 8: How This Solution Is Scalable

**Horizontal scaling dimensions**:

1. **KPI families**
   - Adding a new KPI family means adding one YAML file and running the loader.
   - Zero code changes. Zero downtime. Current families: Contract Hierarchy, Attrition, Employee Count, Terminations, Hours.

2. **Term vocabulary**
   - New stations, customers, or dimensions are added to YAML and loaded into Neo4j.
   - The extractor reads them at startup — no code deploy.

3. **Concurrent users**
   - Neo4j connection pool is sized at 10 (configurable).
   - Ontology reads are lightweight (~2-5ms). The heavy work (SQL generation) happens in the LLM layer, not Neo4j.

4. **Data volume in Neo4j**
   - The ontology is *metadata*, not transactional data.
   - Scale is measured in thousands of nodes, not billions.
   - Current scale: ~5 KPIs, ~4 views, ~15 term categories, ~200 terms — easily fits in Neo4j Community.

5. **Multi-tenant**
   - Separate Neo4j databases or graph namespaces can isolate ontologies per business unit.

---

## Slide 9: Benefits of This Design

| Stakeholder | Benefit |
|-------------|---------|
| **Data Engineers** | KPI logic lives in YAML, not Python. Adding a new metric is a config change, not a code change. |
| **Business Analysts** | Can read the YAML to understand what questions the chatbot supports. |
| **Security Team** | Role-based station/customer filters are explicit nodes in the graph — auditable. |
| **Developers** | No hardcoded SQL fragments. All query logic is data-driven via the ontology. |
| **Ops Team** | Idempotent loader (`MERGE`) means safe re-runs. Neo4j health checks are built-in. |
| **CTO** | The chatbot scales to new domains without engineering sprint overhead. |

**Technical benefits**:
- **Single source of truth**: One YAML file defines a KPI; the graph enforces consistency.
- **Rejection of bad queries**: If a user asks "Attrition by postal code" and the view doesn't support postal codes, the pipeline rejects it *before* generating SQL.
- **Join automation**: Multi-view KPIs (e.g., Hours uses FACTDAILYWORKDETAILS_MS_V + DIMHISTORYEMPLOYEE_V) automatically resolve their JOIN conditions from the graph.

---

## Slide 10: Improvements Over the Current / Previous Design

| Before (Hardcoded) | After (Ontology-Driven) |
|--------------------|-------------------------|
| KPI detection was `if/elif` chains in Python | KPI detection reads synonyms from Neo4j Term nodes |
| Station matching was a hardcoded regex for 3-letter codes | Station matching uses configurable `match_type` (exact, fuzzy_token, fuzzy_partial) loaded from graph |
| Date periods were hardcoded SQL strings in Python | Date periods are parsed by a generic `date_parser` module; SQL expressions live in Term `context` fields |
| Group-by was manually coded per KPI | Group-by is driven by `groupable: true` metadata on TermCategory nodes |
| New KPIs required Python code changes | New KPIs require only a YAML file + loader run |
| Joins were hardcoded in SQL generator | Joins are resolved from `JOINS_TO` relationships in Neo4j |
| No validation of unsupported filters | `unsupported_term_categories` on View nodes triggers explicit rejection |
| No ranking/top-N support | `default_ranking_metric` and `default_ranking_order` on KPI nodes enable generic top-N |
| No threshold filters ("more than 10%") | Regex-based `ThresholdFilter` detection with metric heuristics |
| Entity-by-name required code changes | Canonical name indexing in Neo4j + `canonical_map` resolution in extractor |

---

## Slide 11: Technical Deep-Dive — Building the Ontology

**Step 1: Author the YAML**

```yaml
# ontology/schema/terms.yaml
- name: stations
  column: STATIONCODE
  value_kind: code          # stores MSP, ATL — not full names
  match_type: exact         # 3-4 letter codes
  extractable: true
  groupable: true
  terms:
    - { code: MSP, canonical: "Minneapolis" }
    - { code: ATL, canonical: "Atlanta" }
```

**Step 2: Run the loader**

```python
from ontology.loader import load_all
counts = load_all()  # Idempotent — MERGE creates-or-updates
# {'views': 4, 'joins': 2, 'terms': 215, 'disambiguation': 5, 'kpis': 7}
```

**Step 3: Inspect in Neo4j Browser**

```cypher
MATCH (tc:TermCategory {name:'stations'})<-[:IN_CATEGORY]-(t:Term)
RETURN t.code, t.canonical
```

**Result**:

| t.code | t.canonical |
|--------|-------------|
| MSP    | Minneapolis |
| ATL    | Atlanta     |

---

## Slide 12: Technical Deep-Dive — Querying the Ontology

**Query 1: Load all terms for the intent extractor**

```python
# core/intent_extractor.py — at startup
cat_records = execute_query("MATCH (tc:TermCategory) RETURN tc {.*} AS tc")
term_records = execute_query(
    "MATCH (t:Term) RETURN t.code, t.canonical, t.category, t.context"
)
```

This populates an in-memory cache (`TERM_CATEGORIES`) so extraction is fast at runtime.

**Query 2: Look up a KPI recipe**

```python
# core/ontology_lookup.py
records = execute_query("""
    MATCH (k:KPI {name: $name, status: 'active'})
    OPTIONAL MATCH (k)-[:REQUIRES_STEP]->(s:KPIStep)
    OPTIONAL MATCH (k)-[:HAS_FILTER]->(f:Filter)
    OPTIONAL MATCH (k)-[:USES_VIEW]->(v:View)
    RETURN k {.*} AS kpi,
           collect(DISTINCT s {.*}) AS steps,
           collect(DISTINCT f {.*}) AS filters,
           collect(DISTINCT v.name) AS views
""", {"name": "Attrition Rate"})
```

**Query 3: Resolve joins for a multi-view KPI**

```python
# core/ontology_lookup.py
records = execute_query("""
    UNWIND $views AS view_name
    MATCH (v:View {name: view_name})
    WITH collect(v.name) AS view_set
    MATCH (fv:View)-[j:JOINS_TO]->(tv:View)
    WHERE fv.name IN view_set AND tv.name IN view_set
    RETURN j.type AS join_type, j.condition AS condition,
           fv.name AS from_view, tv.name AS to_view
""", {"views": ["FACTDAILYWORKDETAILS_MS_V", "DIMHISTORYEMPLOYEE_V"]})
```

**Returns**: `INNER JOIN DIMHISTORYEMPLOYEE_V e ON w.EMPLOYEE_ID = e.EMPLOYEE_ID`

---

## Slide 13: Maintainability — How Easy Is This to Maintain?

**Day-to-day changes and who can make them**:

| Change | Effort | Who |
|--------|--------|-----|
| Add a new station (e.g., DEN) | 1 line in YAML + re-run loader | Business Analyst |
| Add a new KPI family | 1 YAML file (~100 lines) + re-run loader | Data Engineer |
| Change attrition formula | Edit `formula:` in YAML + re-run loader | Data Engineer |
| Add a new term category (e.g., job_title) | Add category block in YAML + re-run loader | Data Engineer |
| Change fuzzy matching threshold | Edit `threshold:` in YAML + re-run loader | Data Engineer |
| Deactivate a KPI | Set `status: inactive` in YAML + re-run loader | Data Engineer |
| Add a new view join | Add entry in `joins.yaml` + re-run loader | Data Engineer |

**No code deploy required for any of the above.**

**Validation safety net**:
- `ontology/validator.py` runs checks before loading:
  - All `supported_term_categories` in KPIs must exist as `TermCategory` nodes
  - Extractable terms must have a `column` mapping
  - Period-enabled views must declare a `date_column`
- The loader logs every action (`views_loaded: 4`, `terms_loaded: 215`).

---

## Slide 14: What Data Goes Into Neo4j?

**NOT business data**. No employee records, no payroll rows.

**Only metadata / ontology data**:

| Node Label | Count (approx) | What it stores |
|------------|---------------|----------------|
| `KPI` | 7 | KPI definitions, formulas, output shapes, ranking defaults |
| `KPIStep` | 14 | Ordered computation steps with logic descriptions |
| `Filter` | 25 | WHERE-clause templates per KPI |
| `View` | 4 | Snowflake view names, schemas, columns, date columns |
| `JOINS_TO` (rel) | 2 | Join conditions between views |
| `TermCategory` | 15 | Dimension types with match strategy metadata |
| `Term` | ~215 | Specific values: station codes, customer names, period phrases, status codes |
| `DisambiguationRule` | 5 | Rules to resolve ambiguous terms (e.g., "Delta" as airline vs. region) |
| `User` | N | Authorized stations/customers per user |

**Data size**: Entire graph is ~300 nodes + relationships. Fits in RAM. Query latency: ~2-5ms.

---

## Slide 15: Visualizing the Ontology in Neo4j

**Tool**: Neo4j Browser (free, bundled with Neo4j)

**Example queries for visualization**:

```cypher
// See all KPIs and their views
MATCH (k:KPI)-[:USES_VIEW]->(v:View)
RETURN k, v

// See a single KPI with its full recipe
MATCH (k:KPI {name: 'Attrition Rate'})-[:REQUIRES_STEP]->(s:KPIStep)
MATCH (k)-[:HAS_FILTER]->(f:Filter)
MATCH (k)-[:USES_VIEW]->(v:View)
RETURN k, s, f, v

// See term categories and their terms
MATCH (tc:TermCategory)<-[:IN_CATEGORY]-(t:Term)
RETURN tc, t LIMIT 50

// See view join graph
MATCH (a:View)-[j:JOINS_TO]->(b:View)
RETURN a, j, b
```

**Visual output**: Interactive graph where clicking a node shows all properties. Non-technical stakeholders can understand "Attrition Rate uses this view, which joins to this other view, and accepts these filters."

**Bloom (Enterprise)**: For larger ontologies, Bloom provides point-and-click graph exploration without writing Cypher.

---

## Slide 16: Application Boot-Time Querying

**Pipeline initialization** (`core/pipeline.py`):

```python
class NL2SQLPipeline:
    def __init__(self):
        verify_connectivity()          # Neo4j health check
        load_terms_from_neo4j()      # Cache terms in memory
```

**What happens at startup**:

1. **Connectivity check**: `driver.verify_connectivity()` — fails fast if Neo4j is unreachable.
2. **Term loading**: Two Cypher queries fetch all `TermCategory` metadata and all `Term` values into a Python dictionary (`TERM_CATEGORIES`).
3. **In-memory cache**: After loading, all term matching happens in RAM — no Neo4j round-trips per user question.

**Why this design**:
- Term vocabulary is small (~215 terms). Caching in RAM eliminates latency.
- KPI recipes are fetched on-demand (per question) because the question determines which KPI is relevant.
- If terms change, restart the app or call `load_terms_from_neo4j()` to refresh.

---

## Slide 17: Run-Time Query Answering — The Full Pipeline

**User asks**: *"What is the attrition rate at MSP YTD?"*

**Step-by-step**:

| Step | Component | Neo4j Role | Time |
|------|-----------|-----------|------|
| 1. **Intent Extraction** | `core/intent_extractor` | None (uses in-memory cache) | ~5ms |
| 2. **KPI Lookup** | `core/ontology_lookup.lookup_kpi()` | Fetches KPI recipe, steps, filters, views | ~3ms |
| 3. **View & Join Lookup** | `core/ontology_lookup.get_joins_between_views()` | Fetches join conditions if multi-view | ~2ms |
| 4. **Context Building** | `core/context_builder` | None (uses loaded recipe metadata) | ~3ms |
| 5. **SQL Generation** | `core/sql_generator` | None (calls LLM with structured prompt) | ~800-1500ms |
| 6. **SQL Validation** | `core/sql_validator` | None (schema-aware guardrails) | ~5ms |
| 7. **Execution** | `core/snowflake_executor` | None (runs SQL in Snowflake) | ~500-2000ms |

**Neo4j is the *orchestrator brain* — it provides the plan. The LLM writes the SQL. Snowflake executes it.**

**Key Cypher queries at runtime**:

```cypher
-- Step 2: Load KPI recipe
MATCH (k:KPI {name:'Attrition Rate', status:'active'})
OPTIONAL MATCH (k)-[:REQUIRES_STEP]->(s:KPIStep)
OPTIONAL MATCH (k)-[:HAS_FILTER]->(f:Filter)
OPTIONAL MATCH (k)-[:USES_VIEW]->(v:View)
RETURN k, collect(DISTINCT s), collect(DISTINCT f), collect(DISTINCT v)

-- Step 3: Load joins between views used by the KPI
UNWIND ['AGGEMPCOUNT_ATTRITION_DATA_V_Table'] AS view_name
MATCH (v:View {name: view_name})
WITH collect(v.name) AS view_set
MATCH (fv:View)-[j:JOINS_TO]->(tv:View)
WHERE fv.name IN view_set AND tv.name IN view_set
RETURN j.type, j.condition, fv.name, tv.name
```

---

## Slide 18: Architecture Diagram (Textual)

```
┌──────────────────────────────────────────────────────────────┐
│                        USER QUESTION                          │
│         "What is the attrition rate at MSP YTD?"            │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│              INTENT EXTRACTOR (Python + Regex)                │
│  • Fuzzy matches KPI synonyms from in-memory cache            │
│  • Extracts station (MSP), period (YTD)                     │
│  • Detects grouping, aggregation, thresholds                  │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│              NEO4J ONTOLOGY (Graph Database)                  │
│                                                               │
│   (KPI:Attrition Rate)-[:USES_VIEW]->(View:AGGEMP...)       │
│   (KPI)-[:REQUIRES_STEP]->(Step)                             │
│   (KPI)-[:HAS_FILTER]->(Filter:STATIONCODE)                 │
│   (TermCategory:stations)<-[:IN_CATEGORY]-(Term:MSP)         │
│                                                               │
│   Queries: lookup_kpi(), get_joins_between_views()          │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│              CONTEXT BUILDER (Python)                         │
│  • Rejects unsupported terms (view metadata from Neo4j)       │
│  • Resolves joins (from Neo4j)                              │
│  • Binds {date_col} to actual date column                   │
│  • Builds StructuredContext for LLM prompt                    │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│              SQL GENERATOR (LLM + Prompt Engineering)         │
│  • Receives structured context (views, filters, joins,      │
│    grouping, limit, thresholds, steps)                       │
│  • Generates Snowflake SQL                                   │
│  • _enforce_view_names() guards against wrong table names   │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│              SNOWFLAKE (Data Warehouse)                       │
│  • Executes validated SQL                                    │
│  • Returns results to chatbot                                │
└───────────────────────────────────────────────────────────────┘
```

---

## Slide 19: Call to Action & Next Steps

**What we have today**:
- A working ontology in Neo4j powering 5 KPI families
- Data-driven extraction and SQL generation
- YAML-based governance with idempotent loader
- Regression tests (golden tests) for each domain

**What comes next**:
1. **Expand ontology coverage** — add Revenue, Safety, and On-Time Performance KPIs via YAML
2. **Self-service governance UI** — allow business analysts to edit terms/KPIs via a web UI that writes YAML
3. **Neo4j Enterprise** — enable clustering and Bloom for larger teams
4. **Multi-tenant ontologies** — separate graphs per division
5. **Explainability dashboard** — show users *why* a particular SQL was generated by tracing the ontology path

**The bottom line for executives**:
> We have moved from a "code-driven" chatbot (every new metric requires an engineer) to an "ontology-driven" chatbot (every new metric requires a YAML file). This is the difference between a 2-week sprint and a 2-hour config change.

---

*Document generated from actual codebase: UnifiKPIOntologyEnabledChatbot*
*Last updated: 2026-06-03*
