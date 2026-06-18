# Power BI connection guide

The Gold warehouse (DuckDB file or Azure Synapse) is the single source of truth for
Power BI reports.

## DirectQuery to DuckDB (local / file-based)

1. Install the **DuckDB ODBC driver** (https://github.com/duckdb/duckdb-odbc).
2. In Power BI Desktop → *Get Data* → *ODBC* → paste the DSN string
   `Driver={DuckDB Driver};Database=<absolute path>/data/gold/warehouse.duckdb`.
3. Import these tables/views:
   * `v_national_pressure`
   * `v_regional_risk_latest`
   * `v_top_risk_trusts`
   * `v_forecast_long`
   * `recommendation`
4. Build executive report pages mirroring the web app (`frontend/src/pages/`).

## DirectQuery to Azure Synapse (production)

1. In Power BI Service, *Get Data* → *Azure Synapse Analytics (SQL DW)*.
2. Server = `<synapse-workspace>.sql.azuresynapse.net`, Database = `nhs_gold`.
3. Use **DirectQuery** (not Import) so the report always reflects the latest
   warehouse state after each Airflow run.

## Row-Level Security (RLS)

For multi-ICB / multi-Region deployments, configure RLS in Synapse using
the `region_id` column on `dim_hospital`. Sample RLS predicate:

```sql
CREATE SECURITY POLICY region_filter
ADD FILTER PREDICATE dbo.fn_region_access_predicate(region_id) ON dbo.dim_hospital;
```

## Recommended visuals

* **Executive overview:** KPI cards (Red/Amber/Green counts), line chart of
  `v_national_pressure.avg_bed_occupancy_pct`, choropleth of regional risk.
* **Forecasting:** line + confidence band from `v_forecast_long`.
* **Workforce:** stacked bar of vacancy rate by region; table of
  `recommendation` filtered to Red severity.
