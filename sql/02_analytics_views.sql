-- =====================================================================
--  Analytics views consumed by dashboards and the LLM RAG layer.
-- =====================================================================

-- National daily pressure — used by Executive Overview.
CREATE OR REPLACE VIEW v_national_pressure AS
SELECT
    f.date_key,
    SUM(f.ae_attendances)            AS ae_attendances,
    SUM(f.admissions)                AS admissions,
    SUM(f.discharges)                AS discharges,
    AVG(f.bed_occupancy_pct)         AS avg_bed_occupancy_pct,
    SUM(f.waiting_list_size)         AS total_waiting_list,
    AVG(f.vacancy_rate)              AS avg_vacancy_rate
FROM hospital_activity_fact f
GROUP BY f.date_key
ORDER BY f.date_key;

-- Regional risk latest — used by Risk Map.
CREATE OR REPLACE VIEW v_regional_risk_latest AS
WITH latest AS (SELECT MAX(date_key) AS d FROM risk_score)
SELECT
    h.region_id,
    r.region_name,
    rs.date_key,
    COUNT(*) FILTER (WHERE rs.classification = 'Red')   AS red_count,
    COUNT(*) FILTER (WHERE rs.classification = 'Amber') AS amber_count,
    COUNT(*) FILTER (WHERE rs.classification = 'Green') AS green_count,
    AVG(rs.score) AS avg_score
FROM risk_score rs
JOIN dim_hospital h ON rs.hospital_id = h.hospital_id
JOIN dim_region   r ON h.region_id    = r.region_id
WHERE rs.date_key = (SELECT d FROM latest)
GROUP BY h.region_id, r.region_name, rs.date_key;

-- Forecast long-format (target × horizon × trust) for plotting.
CREATE OR REPLACE VIEW v_forecast_long AS
SELECT
    mf.date_key,
    h.hospital_name,
    s.specialty_name,
    mf.target,
    mf.horizon_days,
    mf.yhat,
    mf.yhat_lower,
    mf.yhat_upper,
    mf.model
FROM ml_forecast mf
LEFT JOIN dim_hospital  h ON mf.hospital_id  = h.hospital_id
LEFT JOIN dim_specialty s ON mf.specialty_id = s.specialty_id;

-- Top 10 at-risk trusts (latest).
CREATE OR REPLACE VIEW v_top_risk_trusts AS
WITH latest AS (SELECT MAX(date_key) AS d FROM risk_score)
SELECT
    h.hospital_name,
    r.region_name,
    rs.classification,
    rs.score,
    rs.date_key
FROM risk_score rs
JOIN dim_hospital h ON rs.hospital_id = h.hospital_id
JOIN dim_region   r ON h.region_id    = r.region_id
WHERE rs.date_key = (SELECT d FROM latest)
ORDER BY rs.score DESC
LIMIT 10;
