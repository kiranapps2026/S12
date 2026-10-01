-- Stage event log: one row per stage outcome of an S0-S11 run. No payload: no user text or
-- model output is stored. tenant_id is NULL only when S0 stopped before identity was known.
CREATE TABLE pipeline_events (
    event_id     BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT,
    trace_id     TEXT,
    request_id   TEXT,
    stage        TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('normal','clarify','deny','error')),
    reason       TEXT,
    duration_ms  DOUBLE PRECISION NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pipeline_events_trace ON pipeline_events (trace_id);
CREATE INDEX idx_pipeline_events_tenant_time ON pipeline_events (tenant_id, recorded_at);

-- A tenant reads only its own events; the application role may insert but the event log is
-- append-only for it (no UPDATE/DELETE grant is given in INSTALLATION.md).
ALTER TABLE pipeline_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON pipeline_events
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant', true));
