-- =============================================================================
-- Week 4 Database Migrations for Campus Chat (PostgreSQL campus_chat)
-- Document Ingestion, Versioning, Website Sync, and Predictive Prefetching
-- =============================================================================

-- 1. Documents Master Table
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    doc_code VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    source_url TEXT,
    upload_source VARCHAR(50) NOT NULL DEFAULT 'upload', -- 'upload', 'sync', 'system'
    uploaded_by VARCHAR(100) DEFAULT 'admin',
    visibility VARCHAR(50) NOT NULL DEFAULT 'public',    -- 'public', 'internal', 'restricted'
    approval_status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'archived'
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    current_version_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_code ON documents(doc_code);
CREATE INDEX IF NOT EXISTS idx_documents_approval ON documents(approval_status);
CREATE INDEX IF NOT EXISTS idx_documents_active ON documents(is_active);

-- 2. Document Versions Table
CREATE TABLE IF NOT EXISTS document_versions (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL DEFAULT 1,
    file_hash VARCHAR(64) NOT NULL, -- SHA-256
    file_name VARCHAR(255) NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    mime_type VARCHAR(100) DEFAULT 'application/pdf',
    storage_path TEXT NOT NULL,
    approval_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    extracted_text_len INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    uploaded_by VARCHAR(100) DEFAULT 'admin',
    approved_by VARCHAR(100),
    approved_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_doc_version UNIQUE (document_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_doc_versions_hash ON document_versions(file_hash);
CREATE INDEX IF NOT EXISTS idx_doc_versions_active ON document_versions(is_active);

-- 3. Document Chunks Table
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chroma_id VARCHAR(100) NOT NULL,
    token_count INTEGER DEFAULT 0,
    content_preview TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_version ON document_chunks(version_id);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_chroma ON document_chunks(chroma_id);

-- 4. Document Ingestion Jobs Table
CREATE TABLE IF NOT EXISTS document_ingestion_jobs (
    id SERIAL PRIMARY KEY,
    version_id INTEGER REFERENCES document_versions(id) ON DELETE SET NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_hash VARCHAR(64),
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed', 'quarantined'
    stage VARCHAR(100) DEFAULT 'queued',
    attempt_count INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON document_ingestion_jobs(status);

-- 5. Document Sync Sources (Allowlisted VJTI Scraping Pages)
CREATE TABLE IF NOT EXISTS document_sync_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL, -- 'circulars', 'academic_notices', 'admissions', 'calendars'
    source_url TEXT NOT NULL UNIQUE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    check_interval_minutes INTEGER NOT NULL DEFAULT 360, -- 6 hours default
    last_checked_at TIMESTAMP WITH TIME ZONE,
    last_status VARCHAR(50) DEFAULT 'never_run',
    error_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Seed initial approved VJTI categories if not present
INSERT INTO document_sync_sources (name, category, source_url, check_interval_minutes)
VALUES
    ('VJTI Academic Notices', 'academic_notices', 'https://vjti.ac.in/academic-notices/', 360),
    ('VJTI Examination Notices', 'circulars', 'https://vjti.ac.in/examination-notices/', 360),
    ('VJTI Admissions Announcements', 'admissions', 'https://vjti.ac.in/admissions/', 360),
    ('VJTI Academic Calendar & Regulations', 'calendars', 'https://vjti.ac.in/academic-calendar/', 360)
ON CONFLICT (source_url) DO NOTHING;

-- 6. Document Sync History
CREATE TABLE IF NOT EXISTS document_sync_history (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES document_sync_sources(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    docs_found INTEGER DEFAULT 0,
    docs_downloaded INTEGER DEFAULT 0,
    docs_updated INTEGER DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'completed',
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_sync_history_date ON document_sync_history(started_at);

-- 7. Document Audit Logs
CREATE TABLE IF NOT EXISTS document_audit_logs (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    version_id INTEGER REFERENCES document_versions(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL, -- 'uploaded', 'approved', 'rejected', 'archived', 'replaced', 'synced'
    performed_by VARCHAR(100) DEFAULT 'admin',
    details JSONB,
    ip_address VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON document_audit_logs(action);

-- 8. Query Transitions (Markov Chain Predictive Prefetching)
CREATE TABLE IF NOT EXISTS query_transitions (
    id SERIAL PRIMARY KEY,
    prev_query_hash VARCHAR(64) NOT NULL,
    prev_query_text TEXT NOT NULL,
    next_query_hash VARCHAR(64) NOT NULL,
    next_query_text TEXT NOT NULL,
    transition_count INTEGER NOT NULL DEFAULT 1,
    last_transition_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_query_transition UNIQUE (prev_query_hash, next_query_hash)
);

CREATE INDEX IF NOT EXISTS idx_query_transitions_prev ON query_transitions(prev_query_hash);

-- 9. Prefetch Metrics
CREATE TABLE IF NOT EXISTS prefetch_metrics (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    trigger_query TEXT NOT NULL,
    predicted_query TEXT NOT NULL,
    prediction_confidence DOUBLE PRECISION NOT NULL,
    prefetch_status VARCHAR(50) NOT NULL, -- 'cached', 'prefetch_hit', 'prefetch_skipped', 'budget_exceeded'
    cache_hit BOOLEAN DEFAULT FALSE,
    latency_saved_ms DOUBLE PRECISION DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_prefetch_metrics_time ON prefetch_metrics(timestamp);
