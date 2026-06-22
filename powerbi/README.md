# Power BI starter report

The Gold warehouse lives in **PostgreSQL (Supabase)** — the single source of
truth for both the web app and Power BI.

## One-click connect (recommended)

1. Double-click **`nhs_supabase.pbids`** — Power BI Desktop opens pre-connected to
   the Supabase Postgres host.
2. When prompted for credentials, choose **Database** and enter:
   * **User name:** `postgres.dtxavwlqmefuhyphjikk` (the pooler form — note the dot + project ref, *not* plain `postgres`)
   * **Password:** your Supabase database password (type it **literally** — no URL-encoding)
3. **⚠️ Uncheck "Encrypt connection".** Power BI's PostgreSQL driver can't validate
   the Supabase pooler certificate, so leaving it on fails with
   *"The remote certificate is invalid according to the validation procedure."*
   Unchecking it lets the handshake through. (Use **Power BI Desktop**, not the web
   Service — the browser connector has no unencrypted option and needs a data gateway.)

> **Offline fallback:** if you'd rather skip the live DB entirely, open
> `nhs_powerbi_data.xlsx` (in this folder) via **Get data → Excel** — same tables,
> no connection needed. Regenerate it with `python scripts/export_powerbi.py`.
4. In the Navigator, tick these analytics views + tables, then **Load**:
   * `v_national_pressure`   — national daily pressure
   * `v_regional_risk_latest` — Red/Amber/Green by region
   * `v_top_risk_trusts`     — top at-risk trusts
   * `v_forecast_long`       — forecasts (target × horizon)
   * `recommendation`        — prescriptive actions
   * `dim_region`, `dim_hospital` — for slicers / maps
   * `ae_dept_state`         — live A&E digital-twin (occupancy, queue, ambulances)
   * `model_metrics`         — back-tested accuracy per model
   * `model_forecast_actual` — predicted-vs-actual hold-out series

> `nhs_supabase.pbids` targets the IPv4 **session pooler** host (Power BI is
> IPv4-only). Edit the `server` line if your Supabase region differs.

## Starter DAX measures

**Create each one separately** — Modeling → **New measure**, paste a *single*
`Name = …` line, press Enter, repeat. (Pasting the whole list into one measure
is a syntax error.) Each measure is **self-contained** (`VAR L = MAX(...)`) so
there's no cross-measure dependency to break. Make sure the table names match
your model — if Power BI imported them as `public <name>`, either rename the
tables to drop the prefix or quote them, e.g. `'public v_national_pressure'`.
`avg_bed_occupancy_pct` is a demand-vs-capacity ratio (can exceed 100%), so it's
surfaced as **Capacity Pressure**, not literal occupancy.

```DAX
Capacity Pressure % = VAR L = MAX ( v_national_pressure[date_key] ) RETURN CALCULATE ( AVERAGE ( v_national_pressure[avg_bed_occupancy_pct] ), v_national_pressure[date_key] = L )
```
```DAX
Total Waiting List = VAR L = MAX ( v_national_pressure[date_key] ) RETURN CALCULATE ( SUM ( v_national_pressure[total_waiting_list] ), v_national_pressure[date_key] = L )
```
```DAX
A&E Attendances = VAR L = MAX ( v_national_pressure[date_key] ) RETURN CALCULATE ( SUM ( v_national_pressure[ae_attendances] ), v_national_pressure[date_key] = L )
```
```DAX
Trusts in Red = CALCULATE ( COUNTROWS ( v_top_risk_trusts ), v_top_risk_trusts[classification] = "Red" )
```
```DAX
Live Occupancy % = VAR L = MAX ( ae_dept_state[minute_ts] ) RETURN CALCULATE ( AVERAGE ( ae_dept_state[occupancy_pct] ), ae_dept_state[minute_ts] = L )
```
```DAX
Ambulances Waiting = VAR L = MAX ( ae_dept_state[minute_ts] ) RETURN CALCULATE ( SUM ( ae_dept_state[ambulances_waiting] ), ae_dept_state[minute_ts] = L )
```
```DAX
Beds Available Now = VAR L = MAX ( ae_dept_state[minute_ts] ) RETURN CALCULATE ( SUM ( ae_dept_state[available_beds] ), ae_dept_state[minute_ts] = L )
```
```DAX
Patients Queued Now = VAR L = MAX ( ae_dept_state[minute_ts] ) RETURN CALCULATE ( SUM ( ae_dept_state[queue_length] ), ae_dept_state[minute_ts] = L )
```
```DAX
Model Accuracy % = AVERAGE ( model_metrics[accuracy] )
```

## Suggested report pages (mirror the web app)

* **Executive overview** — KPI cards (the measures above), line chart of
  `avg_bed_occupancy_pct` over `date_key`, donut of Red/Amber/Green from
  `v_regional_risk_latest`, table of `v_top_risk_trusts`.
* **Forecasting** — line + shaded band from `v_forecast_long` (`yhat`,
  `yhat_lower`, `yhat_upper`), sliced by `target` and `horizon_days`.
* **Workforce** — bar of vacancy rate by region; `recommendation` table filtered
  to High severity.
* **Risk map** — filled map on `dim_region` shaded by `avg_score`.
* **Live operations** — cards from `ae_dept_state` ([Live Occupancy %],
  [Ambulances Waiting]); line of `occupancy_pct` + `queue_length` over `minute_ts`.
* **Evidence & validation** — `model_metrics` accuracy by `target` (bar/cards);
  `model_forecast_actual` line of `actual` vs `predicted` over `date`.

## Refresh

The data is republished to Supabase every 2 hours by the `Refresh data` GitHub
Action. Schedule a matching **Scheduled refresh** in the Power BI Service so the
report tracks it.

## Row-Level Security (multi-ICB)

Filter on `dim_hospital[region_id]` (or `dim_region[region_id]`):

```DAX
[region_id] = LOOKUPVALUE ( UserRegion[region_id], UserRegion[email], USERPRINCIPALNAME () )
```
