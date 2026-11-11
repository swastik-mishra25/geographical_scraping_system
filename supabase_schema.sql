-- =========================================================================
-- Dakini Geographical Lead Scraping & Autonomous Discovery Engine
-- Production Supabase PostgreSQL Schema
-- =========================================================================

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. COMPANIES (Master verified business leads table)
CREATE TABLE IF NOT EXISTS public.companies (
    company_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry_category TEXT NOT NULL,
    industry_subcategory TEXT DEFAULT '',
    country TEXT DEFAULT 'India',
    state TEXT DEFAULT '',
    city TEXT DEFAULT '',
    locality TEXT DEFAULT '',
    website TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    contact_person TEXT DEFAULT '',
    contact_role TEXT DEFAULT '',
    company_size TEXT DEFAULT 'unknown',
    company_age TEXT DEFAULT 'unknown',
    services JSONB DEFAULT '[]'::jsonb,
    location_type TEXT DEFAULT 'unverified',
    verification_status TEXT DEFAULT 'unverified',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_companies_city ON public.companies(LOWER(city));
CREATE INDEX IF NOT EXISTS idx_companies_phone ON public.companies(phone) WHERE phone != '';
CREATE INDEX IF NOT EXISTS idx_companies_category ON public.companies(LOWER(industry_category));
CREATE INDEX IF NOT EXISTS idx_companies_updated ON public.companies(updated_at DESC);

-- 2. COMPANY EVIDENCE (Auditable proof & excerpts from crawled websites)
CREATE TABLE IF NOT EXISTS public.company_evidence (
    evidence_id BIGSERIAL PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES public.companies(company_id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    field_value TEXT NOT NULL,
    source_url TEXT NOT NULL,
    evidence_excerpt TEXT DEFAULT '',
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verification_status TEXT DEFAULT 'verified'
);

CREATE INDEX IF NOT EXISTS idx_evidence_company_id ON public.company_evidence(company_id);
CREATE INDEX IF NOT EXISTS idx_evidence_field ON public.company_evidence(field_name);

-- 3. DOMAIN POLICY (Robots.txt compliance, polite delay & safety blocks)
CREATE TABLE IF NOT EXISTS public.domain_policy (
    domain TEXT PRIMARY KEY,
    robots_status TEXT DEFAULT 'unknown',
    terms_review_status TEXT DEFAULT 'unreviewed',
    crawl_permission_status TEXT DEFAULT 'allowed',
    user_agent TEXT DEFAULT '',
    crawl_delay NUMERIC DEFAULT 0.0,
    last_policy_check TEXT DEFAULT '',
    block_reason TEXT DEFAULT ''
);

-- 4. DISCOVERED URLS (Public-web discovery candidates & discovery diagnostics)
CREATE TABLE IF NOT EXISTS public.discovered_urls (
    url_id BIGSERIAL PRIMARY KEY,
    normalized_url TEXT NOT NULL,
    domain TEXT NOT NULL,
    discovery_query TEXT DEFAULT '',
    discovery_method TEXT DEFAULT 'public_web',
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    relevance_status TEXT DEFAULT 'pending',
    crawl_status TEXT DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_disc_urls_domain ON public.discovered_urls(domain);
CREATE INDEX IF NOT EXISTS idx_disc_urls_crawl_status ON public.discovered_urls(crawl_status);

-- 5. CRAWL FRONTIER (Priority queue for parallel multi-metro crawler)
CREATE TABLE IF NOT EXISTS public.crawl_frontier (
    frontier_id BIGSERIAL PRIMARY KEY,
    url_id BIGINT,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    priority INT DEFAULT 10,
    depth INT DEFAULT 0,
    status TEXT DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    next_attempt_at NUMERIC DEFAULT 0,
    last_error TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_frontier_status ON public.crawl_frontier(status, priority DESC);

-- 6. RESEARCH RUNS (Audit trail for targeted & autonomous research runs)
CREATE TABLE IF NOT EXISTS public.research_runs (
    run_id TEXT PRIMARY KEY,
    industry TEXT NOT NULL,
    country TEXT DEFAULT 'India',
    state TEXT DEFAULT '',
    city TEXT NOT NULL,
    locality TEXT DEFAULT '',
    trigger_type TEXT DEFAULT 'api',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TEXT DEFAULT '',
    execution_status TEXT DEFAULT 'queued',
    urls_discovered INT DEFAULT 0,
    urls_crawled INT DEFAULT 0,
    businesses_identified INT DEFAULT 0,
    businesses_validated INT DEFAULT 0,
    export_location TEXT DEFAULT '',
    error_message TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_city ON public.research_runs(LOWER(city));
CREATE INDEX IF NOT EXISTS idx_runs_status ON public.research_runs(execution_status);

-- 7. RESEARCH CHECKPOINTS (Incremental recovery checkpoints)
CREATE TABLE IF NOT EXISTS public.research_checkpoints (
    checkpoint_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    last_processed_item TEXT DEFAULT '',
    checkpoint_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON public.research_checkpoints(run_id);

-- Enable Row Level Security (RLS) and permit service/anon read policies
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.domain_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovered_urls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crawl_frontier ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_checkpoints ENABLE ROW LEVEL SECURITY;

-- Allow public read access (or authenticated) for leads viewing
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow public read access on companies') THEN
        CREATE POLICY "Allow public read access on companies" ON public.companies FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on companies') THEN
        CREATE POLICY "Allow service role full access on companies" ON public.companies FOR ALL USING (true);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow public read access on company_evidence') THEN
        CREATE POLICY "Allow public read access on company_evidence" ON public.company_evidence FOR SELECT USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on company_evidence') THEN
        CREATE POLICY "Allow service role full access on company_evidence" ON public.company_evidence FOR ALL USING (true);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on domain_policy') THEN
        CREATE POLICY "Allow service role full access on domain_policy" ON public.domain_policy FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on discovered_urls') THEN
        CREATE POLICY "Allow service role full access on discovered_urls" ON public.discovered_urls FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on crawl_frontier') THEN
        CREATE POLICY "Allow service role full access on crawl_frontier" ON public.crawl_frontier FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on research_runs') THEN
        CREATE POLICY "Allow service role full access on research_runs" ON public.research_runs FOR ALL USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service role full access on research_checkpoints') THEN
        CREATE POLICY "Allow service role full access on research_checkpoints" ON public.research_checkpoints FOR ALL USING (true);
    END IF;
END $$;

