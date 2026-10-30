# System Architecture

```text
Browser (Existing UI)
   |
   v
FastAPI (/api/scrape)
   |
   +--> Geographic Resolution (Nominatim with in-memory caching and polite throttling)
   |
   +--> Multi-Source Discovery Pipeline:
   |        |
   |        +--> 1. OpenStreetMap / Overpass (with mirror failover)
   |        +--> 2. Overture Maps Places (DuckDB Remote GeoParquet on AWS S3)
   |        +--> 3. SearXNG Metasearch (local Docker endpoint with fail-fast)
   |        +--> 4. Wikidata Query Service (SPARQL + Web API fallback)
   |        +--> 5. India MCA Company Master Data (Streaming local CSV/ZIP)
   |        +--> 6. AllThePlaces Adapter (Local GeoJSON dataset or published run)
   |        +--> 7. Common Crawl (Index API historical candidate corroboration)
   |
   +--> Normalization & Indexed Deduplication (O(N) hash indexes on CIN, domain, name+city)
   |
   +--> Public Website Enrichment:
   |        |
   |        +--> robots.txt compliance & in-memory caching
   |        +--> Homepage inspection & link extraction (tel: / mailto:)
   |        +--> Contact page inspection
   |
   +--> Contact Validation (Indian mobile +91, business email, website format, ownership)
   |
   +--> Dakini AI ICP Lead Scoring (Preserved 100-point model & established weights)
   |
   +--> Final Deduplication & Prioritization
   |
   +--> CSV Export (data/<city>_<category>_leads.csv)
   |
   v
Qualified Lead Dataset (Strictly compatible API JSON & downloadable CSV)
```

## Processing Order

1. Receive `city`, `state`, `category`, and `limit` from existing UI / API request.
2. Resolve geographic coordinates and bounding box via Nominatim.
3. Discover candidates concurrently across all active sources with isolated error handling.
4. Normalize records and perform hash-indexed deduplication to prevent duplicate enrichment.
5. Inspect official company websites for published contacts, adhering to `robots.txt`.
6. Validate contact formats (`+91` Indian mobile, RFC 5322 email, canonical domain).
7. Calculate evidence-based lead qualification score using the preserved scoring formula.
8. Deduplicate and sort leads by qualification score and contact completeness.
9. Export qualified leads to UTF-8 CSV.
10. Return strictly compatible JSON response to the existing frontend.
