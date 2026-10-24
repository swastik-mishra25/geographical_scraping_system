# System Architecture

```text
Browser
   |
   v
FastAPI
   |
   +--> Geographic Discovery ----> OpenStreetMap / Overpass
   |
   +--> Public Website Enrichment
   |        |
   |        +--> robots.txt check
   |        +--> Homepage
   |        +--> Public Contact page
   |
   +--> Validation
   |
   +--> Lead Scoring
   |
   +--> Deduplication
   |
   +--> CSV Export
   |
   v
Qualified Lead Dataset
```

## Processing order

1. Receive city/category/limit.
2. Discover candidate businesses.
3. Enrich available public websites.
4. Validate website, phone and email formats.
5. Calculate evidence-based lead score.
6. Deduplicate records.
7. Return results to the frontend.
8. Save CSV output.
