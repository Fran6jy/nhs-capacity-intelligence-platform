-- =====================================================================
--  NHS Capacity & Demand Intelligence — Star Schema (Gold layer)
--  Compatible with DuckDB, PostgreSQL, Azure Synapse.
--  Author: NHS Platform Team
-- =====================================================================

-- ------------------------- DIM TABLES ---------------------------------

CREATE TABLE IF NOT EXISTS dim_date (
    date_key         DATE        PRIMARY KEY,
    year             INTEGER     NOT NULL,
    quarter          INTEGER     NOT NULL,
    month            INTEGER     NOT NULL,
    month_name       VARCHAR(20) NOT NULL,
    week             INTEGER     NOT NULL,
    day_of_week      INTEGER     NOT NULL, -- 1=Mon ... 7=Sun
    day_name         VARCHAR(20) NOT NULL,
    is_weekend       BOOLEAN     NOT NULL,
    season           VARCHAR(10) NOT NULL, -- Winter | Spring | Summer | Autumn
    flu_season_flag  BOOLEAN     NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_hospital (
    hospital_id      VARCHAR(16) PRIMARY KEY,
    hospital_name    VARCHAR(120) NOT NULL,
    trust_code       VARCHAR(16)  NOT NULL,
    trust_name       VARCHAR(120) NOT NULL,
    region_id        VARCHAR(16)  NOT NULL,
    hospital_type    VARCHAR(40)  NOT NULL,  -- Acute | Specialist | Community
    bed_capacity     INTEGER      NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_specialty (
    specialty_id     VARCHAR(16) PRIMARY KEY,
    specialty_name   VARCHAR(80) NOT NULL,
    category         VARCHAR(40) NOT NULL,  -- Surgery | Medicine | Diagnostic
    is_emergency     BOOLEAN     NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_region (
    region_id        VARCHAR(16) PRIMARY KEY,
    region_name      VARCHAR(80) NOT NULL,
    icb_code         VARCHAR(16),
    country          VARCHAR(40) NOT NULL,
    population       INTEGER
);

-- ------------------------- FACT TABLE ---------------------------------

CREATE TABLE IF NOT EXISTS hospital_activity_fact (
    activity_id          BIGINT      PRIMARY KEY,
    date_key             DATE        NOT NULL,
    hospital_id          VARCHAR(16) NOT NULL,
    specialty_id         VARCHAR(16) NOT NULL,
    region_id            VARCHAR(16) NOT NULL,
    admissions           INTEGER,
    discharges           INTEGER,
    bed_occupancy_pct    NUMERIC(5,2),
    bed_occupancy_count  INTEGER,
    waiting_list_size    INTEGER,
    median_wait_days     NUMERIC(8,2),
    staff_count          INTEGER,
    vacancies            INTEGER,
    vacancy_rate         NUMERIC(5,2),
    ae_attendances       INTEGER,
    referrals            INTEGER,
    flu_index            NUMERIC(5,2),
    covid_index          NUMERIC(5,2),
    avg_temp_c           NUMERIC(4,1),
    FOREIGN KEY (date_key)     REFERENCES dim_date(date_key),
    FOREIGN KEY (hospital_id)  REFERENCES dim_hospital(hospital_id),
    FOREIGN KEY (specialty_id) REFERENCES dim_specialty(specialty_id),
    FOREIGN KEY (region_id)    REFERENCES dim_region(region_id)
);

-- ------------------------- ANALYTICS TABLES ---------------------------

CREATE TABLE IF NOT EXISTS ml_forecast (
    forecast_id          BIGINT      PRIMARY KEY,
    date_key             DATE        NOT NULL,
    hospital_id          VARCHAR(16),
    specialty_id         VARCHAR(16),
    target               VARCHAR(40) NOT NULL,  -- bed_occupancy | waiting_time | ae | workforce
    horizon_days         INTEGER     NOT NULL,  -- 30 / 60 / 90
    yhat                 NUMERIC(10,2),
    yhat_lower           NUMERIC(10,2),
    yhat_upper           NUMERIC(10,2),
    model                VARCHAR(40) NOT NULL   -- prophet | xgboost | lightgbm
);

CREATE TABLE IF NOT EXISTS risk_score (
    risk_id              BIGINT      PRIMARY KEY,
    date_key             DATE        NOT NULL,
    hospital_id          VARCHAR(16) NOT NULL,
    score                NUMERIC(6,3),
    classification       VARCHAR(8)  NOT NULL,  -- Green | Amber | Red
    components_json      JSON,
    FOREIGN KEY (hospital_id) REFERENCES dim_hospital(hospital_id)
);

CREATE TABLE IF NOT EXISTS recommendation (
    recommendation_id    BIGINT      PRIMARY KEY,
    date_key             DATE        NOT NULL,
    hospital_id          VARCHAR(16) NOT NULL,
    severity             VARCHAR(8)  NOT NULL,
    category             VARCHAR(40) NOT NULL,  -- Staffing | Capacity | Workload | Pathway
    action               TEXT        NOT NULL,
    expected_impact      TEXT
);

-- ------------------------- INDEXES (Postgres/Synapse) -----------------
-- DuckDB will not use these but ignores unknown syntax only in PG;
-- wrap in conditional execution when running on DuckDB.

-- CREATE INDEX IF NOT EXISTS ix_fact_date      ON hospital_activity_fact(date_key);
-- CREATE INDEX IF NOT EXISTS ix_fact_hospital  ON hospital_activity_fact(hospital_id);
-- CREATE INDEX IF NOT EXISTS ix_fact_specialty ON hospital_activity_fact(specialty_id);
-- CREATE INDEX IF NOT EXISTS ix_fact_region    ON hospital_activity_fact(region_id);
-- CREATE INDEX IF NOT EXISTS ix_forecast_date  ON ml_forecast(date_key, target);
