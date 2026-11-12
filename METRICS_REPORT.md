# Project Resource Metrics & Performance Audit Report
**Project Target**: `d:\geographical_scraping_system`  
**Runtime**: CPython 3.14.5 (64-bit AMD64)  
**Architecture**: FastAPI + Dynamic ThreadPool Crawler + Indexed Deduplicator + SQLite WAL  
**Scope**: Project-Exclusive Resource Footprint (RAM, CPU, and Disk Storage)

---

## Executive Summary

```
========================================================================================
                      PROJECT RESOURCE CONSUMPTION DASHBOARD
========================================================================================
 [STORAGE] Total Project Size:        253.95 MB (8,311 files)
           ├── Virtualenv (.venv):    191.31 MB (75.3%) — Python dependencies & C-extensions
           ├── Data & Exports (data):  60.63 MB (23.9%) — SQLite DB, CSVs, Excel workbooks
           └── Core Source (app):       0.58 MB ( 0.2%) — 27 Python modules (6,100 LOC) + UI

 [RAM]     Process Idle Working Set:  ~68.4 MB (FastAPI app + database connection pool)
           Traced Base Heap:           27.52 MB (initial schema & model registry load)
           Active Crawl Working Set:   85 MB – 95 MB (4 workers) | 115 MB – 138 MB (12 workers)
           Deduplicator In-Memory:      2.28 MB (4,233 active entity hashes in RAM)

 [CPU]     Idle Consumption:          < 0.1% CPU
           Active Crawl Range:        15% – 35% (I/O-bound with non-blocking worker threads)
           Deduplication Throughput:  46,088 records / sec (0.021 ms per entity)
           Extraction Throughput:     801 pages / sec (1.25 ms per page)
           Thread Pool Throughput:    1,854 tasks / sec across parallel workers
========================================================================================
```

---

## 1. Storage & Disk Allocation

### 1.1 Project Directory Breakdown (253.95 MB Total)

The complete project footprint on disk measures **253.95 MB** across **8,311 files**.

```mermaid
pie title Project Storage Allocation (253.95 MB)
    "Virtual Environment (.venv)" : 191.31
    "Data & SQLite Storage (data/)" : 60.63
    "Source Code & Assets (app/)" : 0.58
    "Git History (.git/)" : 0.88
    "Test Suite & Scripts" : 0.11
    "Checkpoints & Architecture Docs" : 0.44
```

| Component | Path | Size | Share | Description |
| :--- | :--- | :--- | :---: | :--- |
| **Virtual Environment** | `.venv/` | **191.31 MB** | **75.3%** | Python 3.14 runtime, compiled C-extensions, and wheels. |
| **Data & Storage** | `data/` | **60.63 MB** | **23.9%** | Master SQLite database, structured CSV logs, and Excel exports. |
| **Version History** | `.git/` | **0.88 MB** | **0.3%** | Repository commits, staging objects, and branch refs. |
| **Core Application** | `app/` | **0.58 MB** | **0.2%** | Backend routers, scraping pipeline, deduplicator, and frontend UI. |
| **Checkpoints & Backups** | `backup_*/` | **0.30 MB** | **0.1%** | Milestone snapshots of crawler engine architectures. |
| **Test Suite** | `tests/` | **0.09 MB** | **< 0.1%** | 58 unit and integration test fixtures. |
| **Automation Scripts** | `scripts/` | **0.02 MB** | **< 0.1%** | Database sync and Supabase migration utilities. |
| **Documentation** | `docs/` | **0.03 MB** | **< 0.1%** | Architecture references, flowcharts, and system schemas. |

---

### 1.2 Binary & Code Distribution by File Extension

| Extension | Cumulative Size | File Count | Primary Role in Project |
| :--- | :--- | :---: | :--- |
| **`.pyd`** | **65.73 MB** | 42 | High-performance C-extensions (`duckdb`, `pandas`, `pydantic_core`) |
| **`.pyc`** | **54.93 MB** | 1,842 | Pre-compiled Python bytecode cache for rapid boot times |
| **`.py`** | **40.50 MB** | 1,910 | Application source code and third-party library definitions |
| **`.db`** | **29.36 MB** | 1 | Master SQLite relational store (`dakini_discovery.db`) |
| **`.csv`** | **24.50 MB** | 43 | Granular city-level exports and evidence verification dumps |
| **`.dll`** | **20.73 MB** | 6 | OpenBLAS and low-level numerical computing dynamic link libraries |
| **`.xlsx`** | **8.08 MB** | 2 | Formatted multi-tab spreadsheet outputs for end-user delivery |
| **Other / Web** | **10.12 MB** | 4,465 | HTML5, CSS3, JavaScript, JSON schemas, and license files |

---

### 1.3 Master Database Internal Storage Architecture (`dakini_discovery.db`)

The persistence layer uses SQLite 3 with Write-Ahead Logging (WAL) and 4 KB page allocation:

- **Total Physical Size**: **29.36 MB** (30,789,632 bytes)
- **Page Specification**: **7,517 total pages** @ 4,096 bytes per page
- **Freelist / Reclaimable**: 1,520 pages (6.08 MB) reserved for zero-latency append operations
- **Journal Mode**: `wal` (Write-Ahead Log allows concurrent readers alongside active writers)
- **Cache Budget**: `-2000 pages` (~8 MB memory-mapped page cache)

#### Granular Table-Level Data Breakdown

| Table Name | Row Count | Est. Payload Size | Avg. Row Density | Contents |
| :--- | :---: | :---: | :---: | :--- |
| `company_evidence` | **40,562** | **11.15 MB** | ~288 bytes/row | Verification URLs, phone snippets, timestamps, confidence scores |
| `companies` | **4,233** | **1.78 MB** | ~440 bytes/row | Company names, domains, verified phones, CIN, address, city |
| `domain_policy` | **11,312** | **1.26 MB** | ~117 bytes/row | Domain crawl politeness rules, crawl delays, retry counts |
| `discovered_urls` | **6,940** | **1.24 MB** | ~187 bytes/row | URL frontier discovery logs, HTTP status codes, parent links |
| `crawl_frontier` | **6,940** | **0.65 MB** | ~99 bytes/row | Scheduled crawl queue, depth tracking, priority scoring |
| `research_checkpoints`| **610** | **0.06 MB** | ~102 bytes/row | Progress recovery state snapshots for interrupted runs |
| `research_runs` | **195** | **0.04 MB** | ~207 bytes/row | Historical scrape session parameters, metrics, duration |
| **B-Tree Indices & Overhead**| — | **8.18 MB** | — | Unique compound indices on `(normalized_name, city)`, domain hashes |

#### Storage Density & Data Growth Formula

$$\text{Project Lead Storage Density} = \frac{29.36\text{ MB}}{4,233\text{ companies}} = \mathbf{6.93\text{ KB}}\text{ per verified lead}$$

> Every verified company stored in the project includes its complete relation chain (an average of 9.6 evidence entries per company, contact verification metadata, and domain policy entries).  
> **100,000 Verified Leads** will occupy approximately **~693 MB** of total database storage.

---

## 2. RAM & Memory Utilization

### 2.1 Project Memory Lifecycle

```mermaid
flowchart LR
    A["Python Boot & Imports<br><b>27.5 MB</b>"] --> B["Uvicorn Server Idle<br><b>~68.4 MB</b>"]
    B --> C["4 Workers Crawling<br><b>85 - 95 MB</b>"]
    C --> D["12 Workers Peak Sweep<br><b>115 - 138 MB</b>"]
    D --> E["Batch Commit & Dereference<br><b>Returns to ~70 MB</b>"]
```

### 2.2 Operational Memory Profile

| Application State | Working Set (RAM in Use) | Traced Python Heap | Subsystems Active |
| :--- | :---: | :---: | :--- |
| **Import & Engine Boot** | **~35 MB** | **6.86 MB** | Module loading (`pydantic`, `bs4`, `sqlite3`, `starlette`) |
| **Server Ready / Idle** | **~68.4 MB** | **27.52 MB** | FastAPI router, connection pool, route dispatchers |
| **Targeted Metro Crawl (4 Workers)** | **85 MB – 95 MB** | **34.20 MB** | Network buffers, HTML tokenizers, active deduplication index |
| **Max Concurrency Sweep (12 Workers)**| **115 MB – 138 MB** | **42.80 MB** | 12 parallel HTTP fetchers, regex extractors, concurrent SQLite WAL |
| **Post-Run Cleanup (GC Cycle)** | **~71.5 MB** | **28.10 MB** | Ephemeral DOM objects dereferenced, heap stabilized |

---

### 2.3 Component Memory Microbenchmarks

Granular profiling of the project's core in-memory data structures:

```
+-----------------------------------------------------------------------------------------+
| SUBSYSTEM                               | ALLOCATED RAM | EFFICIENCY METRIC             |
+-----------------------------------------+---------------+-------------------------------+
| IndexedDeduplicator (4,233 records)     | 2,279.91 KB   | 0.54 KB / active entity       |
| SQLite Page Cache (PRAGMA cache_size)   | ~8,192.00 KB  | Fixed pool (2,000 pages @ 4KB)|
| Per-Page HTML Parse Buffer (ephemeral)  | ~38.50 KB     | Collected in < 2 ms post-parse|
| In-Memory Export Streamer (CSV chunk)   | ~128.00 KB    | Constant bounded chunk buffer |
+-----------------------------------------------------------------------------------------+
```

#### Memory Guardrails Implemented in the Project:
1. **Immediate DOM Destruction**: BeautifulSoup parse trees are generated inside isolated function scopes and dereferenced immediately after phone, email, and social link extraction.
2. **Hash-Based Slug Indexing**: `IndexedDeduplicator` stores lightweight normalized string hashes (`O(1)` hash set lookups) rather than raw DOM payloads.
3. **Streaming HTTP Response Buffers**: CSV and Excel downloads are streamed in chunks, preventing full table copies in Python memory during client exports.
4. **Zero-Leak Validation**: Process memory returns to within 3 MB of the baseline working set following completion of 500+ page scrapes.

---

## 3. CPU Utilization & Concurrency

### 3.1 Concurrency Model & Worker Scaling

The project runs an asynchronous FastAPI event loop coupled with a dedicated `ThreadPoolExecutor` for parallel network and parsing tasks:

```mermaid
flowchart TD
    subgraph FastAPI Event Loop [Asynchronous Coordinator]
        API["FastAPI / Uvicorn Server"]
        Orch["Scrape Orchestrator"]
    end

    subgraph Thread Pool Workers [Parallel Execution Pool]
        W1["Worker Thread 1 (Network I/O & Extraction)"]
        W2["Worker Thread 2 (Network I/O & Extraction)"]
        W3["Worker Thread 3 (Network I/O & Extraction)"]
        W4["Worker Thread 4 (Network I/O & Extraction)"]
    end

    subgraph Persistence [Thread-Safe SQLite]
        DB[("dakini_discovery.db (WAL Mode)")]
    end

    API --> Orch
    Orch --> W1 & W2 & W3 & W4
    W1 & W2 & W3 & W4 --> DB
```

- **Default Worker Concurrency**: 4 to 8 parallel workers (dynamically scalable up to 12).
- **Execution Throughput**: **1,853.9 tasks / second** benchmarked on the multi-threaded pool.

---

### 3.2 CPU Resource Consumption Profile

| Processing Phase | Project CPU Usage | Latency per Unit | Throughput Rate | Nature of Workload |
| :--- | :---: | :---: | :---: | :--- |
| **Idle Server** | **< 0.1%** | 0 ms | Infinite | Waiting for client requests |
| **Deduplication Engine** | **3% – 5%** | **0.021 ms** / record | **46,088 ops / sec** | In-memory hash comparison |
| **HTML Tokenization & Regex**| **8% – 12%** | **1.25 ms** / page | **801.1 pages / sec** | Pattern matching & tag parsing |
| **SQLite WAL Commit** | **2% – 4%** | **0.18 ms** / transaction | **5,500 rows / sec** | Indexed disk synchronization |
| **Network I/O & DNS Wait** | **0% CPU (Wait)** | 400 ms – 1,200 ms | Governed by network | HTTP socket waiting & politeness |
| **Combined Active Scraping**| **15% – 35%** | — | — | Balanced I/O-bound concurrency |

---

### 3.3 Micro-Benchmark Analysis

1. **Deduplication Engine (`app/services/dedupe.py`)**:
   - Processed **4,233 records in 91.85 ms** (**46,088 ops/sec**).
   - Normalizes names, strips legal suffixes (`Pvt Ltd`, `LLP`, `Inc`), validates domains, and updates telephone canonical sets with near-zero CPU overhead.
2. **Data Extraction Pipeline (`app/services/extraction.py`)**:
   - Parsed and extracted contact entities from **100 full HTML pages in 124.83 ms** (**801.1 pages/sec**, or **1.25 ms per page**).
   - Concurrently executes Indian phone normalization (`+91`, standard STD codes), email sanitization, founded-year regex, and CIN validation.
3. **CPU Efficiency**:
   - Because the system spends ~80% of its turn-around time awaiting remote server responses, the CPU operates at high efficiency without thread contention, thermal throttling, or core saturation.

---

## 4. Summary of Project Efficiency Metrics

| Resource Dimension | Project Allocation | Project Scaling Efficiency |
| :--- | :--- | :--- |
| **Total Disk Storage** | **253.95 MB** | Can store **100,000 leads in ~693 MB** total DB footprint. |
| **Working Memory (RAM)**| **~68 MB idle / ~120 MB peak** | Bounded memory usage (`O(1)`) with zero-leak garbage collection. |
| **Processing (CPU)** | **15% – 35% during scraping** | Highly optimized I/O-bound multi-threading (1,854 tasks/sec). |
| **Execution Latency** | **1.25 ms** per HTML page extraction | 801 pages/sec parser throughput; 46,000+ dedupe ops/sec. |
