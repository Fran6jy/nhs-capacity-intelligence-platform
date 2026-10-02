import { useMemo, useState } from "react";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ShieldCheck } from "lucide-react";
import {
  useForecasts,
  useNhsForecast,
  useNhsForecastMetrics,
  useRttHistory,
  useNhsAe,
  type MonthlyMetric,
} from "../lib/api";
import { GlassCard, SectionTitle, Skeleton } from "../components/ui";
import { chartTooltip } from "../components/chart";
import clsx from "clsx";

const TARGETS = [
  { id: "bed_occupancy", label: "Bed occupancy" },
  { id: "ae_demand", label: "A&E demand" },
  { id: "waiting_time", label: "Waiting time" },
  { id: "vacancy_rate", label: "Vacancy rate" },
];
const HORIZONS = [30, 60, 90];

const fmt = (n: number, unit: string) =>
  unit === "%" ? `${n.toFixed(1)}%` : n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n.toLocaleString("en-GB", { maximumFractionDigits: 0 });

/** Skill against "same month last year" — the baseline that matters for annual-cycle data. */
function SkillBadge({ m }: { m: MonthlyMetric | undefined }) {
  if (!m) return null;
  const pct = Math.round(m.skill * 100);
  const tone = m.skill >= 0.3 ? "text-risk-green ring-risk-green/40 bg-risk-green/10"
             : m.skill > 0 ? "text-risk-amber ring-risk-amber/40 bg-risk-amber/10"
             : "text-risk-red ring-risk-red/40 bg-risk-red/10";
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1", tone)}
          title={`Chosen from ${m.candidates_tried} candidates on ${m.folds} rolling-origin folds · MAE ${m.mae} vs seasonal naive ${m.baseline_mae} · MASE ${m.mase}`}>
      <ShieldCheck className="h-3.5 w-3.5" />
      <span className="font-normal opacity-90">{m.model.replace(/_/g, " ")}</span>
      · {pct > 0 ? "+" : ""}{pct}% skill vs same month last year
      {m.mase != null && <span className="font-normal opacity-80">· MASE {m.mase}</span>}
    </span>
  );
}

/** Real published series + the 12-month forecast, on one time axis. */
function RealForecastPanel() {
  const fc = useNhsForecast();
  const metrics = useNhsForecastMetrics();
  const rtt = useRttHistory(60);
  const ae = useNhsAe();
  const targets = fc.data?.targets ?? [];
  const [target, setTarget] = useState<string | null>(null);
  const active = target && targets.includes(target) ? target : targets[0];

  const data = useMemo(() => {
    if (!active || !fc.data) return [];
    const series = fc.data.series.filter((s) => s.target === active);
    const unit = series[0]?.unit ?? "";
    // Actual history for the chosen target, from whichever real table carries it.
    const hist: { period: string; actual: number }[] = [];
    if (active.startsWith("RTT") && rtt.data?.series) {
      for (const r of rtt.data.series) {
        const v = active === "RTT waiting list" ? r.total_waiting
                : active === "RTT within 18 weeks" ? r.within_18_weeks_pct
                : r.over_52_weeks;
        hist.push({ period: r.period, actual: v });
      }
    } else if (ae.data?.national) {
      for (const r of [...ae.data.national].reverse()) {
        const v = active === "A&E attendances" ? r.attendances
                : active === "A&E four-hour performance" ? r.four_hour_performance_pct
                : r.emergency_admissions;
        hist.push({ period: r.period, actual: v });
      }
    }
    const rows = hist.slice(-36).map((h) => ({ period: h.period, actual: h.actual }));
    for (const s of series) rows.push({ period: s.period, yhat: s.yhat, band: [s.yhat_lower, s.yhat_upper] } as never);
    return { rows, unit };
  }, [active, fc.data, rtt.data, ae.data]);

  const rows = Array.isArray(data) ? [] : data.rows;
  const unit = Array.isArray(data) ? "" : data.unit;
  const metric = metrics.data?.metrics.find((m) => m.target === active);

  if (fc.isLoading) return <Skeleton className="h-96" />;
  if (!fc.data?.available || targets.length === 0) {
    return <p className="text-sm text-slate-400">Real-data forecasts not loaded yet — run <code className="text-nhs-cyan">scripts/ingest_nhs_real.py</code>.</p>;
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {targets.map((t) => (
          <button key={t} onClick={() => setTarget(t)}
            className={clsx("rounded-xl px-3 py-1.5 text-sm font-medium transition-all ring-1",
              active === t ? "bg-risk-green/15 text-risk-green ring-risk-green/40" : "bg-white/[0.03] text-slate-400 ring-white/10 hover:text-white")}>
            {t}
          </button>
        ))}
        <div className="ml-auto"><SkillBadge m={metric} /></div>
      </div>
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
          <defs>
            <linearGradient id="realband" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22c55e" stopOpacity={0.25} />
              <stop offset="100%" stopColor="#22c55e" stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis dataKey="period" tick={{ fill: "#94a3b8", fontSize: 11 }} minTickGap={36} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} domain={["auto", "auto"]} width={64}
                 tickFormatter={(v) => fmt(Number(v), unit)} />
          <Tooltip content={chartTooltip} />
          <Area type="monotone" dataKey="band" name="80% conformal band" stroke="none" fill="url(#realband)" connectNulls={false} />
          <Line type="monotone" dataKey="actual" name="Published" stroke="#94a3b8" strokeWidth={2} dot={false} connectNulls={false} />
          <Line type="monotone" dataKey="yhat" name="Forecast" stroke="#22c55e" strokeWidth={2.5} dot={false} connectNulls={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-2 text-xs text-slate-500">
        Grey is NHS England's published monthly figure; green is a 12-month forecast from whichever
        candidate model won the rolling-origin back-test for this series (named in the badge), with an
        80% band sized from that model's own held-out errors rather than a fixed multiplier. Skill is
        measured against "same month last year"; if nothing beats it, the naive is the forecast and
        the badge says so.
      </p>
    </>
  );
}

export default function Forecasting() {
  const [target, setTarget] = useState("bed_occupancy");
  const [horizon, setHorizon] = useState(90);
  const q = useForecasts(target, horizon);

  // Aggregate to a national mean per date for a clean line + band.
  const byDate = new Map<string, { sum: number; lo: number; hi: number; n: number }>();
  for (const r of q.data ?? []) {
    const e = byDate.get(r.date_key) ?? { sum: 0, lo: 0, hi: 0, n: 0 };
    e.sum += r.yhat ?? 0;
    e.lo += r.yhat_lower ?? 0;
    e.hi += r.yhat_upper ?? 0;
    e.n += 1;
    byDate.set(r.date_key, e);
  }
  const data = [...byDate.entries()]
    .map(([date_key, e]) => ({
      date_key,
      yhat: +(e.sum / e.n).toFixed(2),
      band: [+(e.lo / e.n).toFixed(2), +(e.hi / e.n).toFixed(2)] as [number, number],
    }))
    .sort((a, b) => a.date_key.localeCompare(b.date_key));

  return (
    <div>
      <SectionTitle title="Forecasting" subtitle="12-month national outlook on published NHS data · 30/60/90-day projections on the modelled daily series" />

      <GlassCard>
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <h3 className="font-semibold text-white">National outlook — published NHS England series</h3>
          <span className="rounded-full bg-risk-green/15 px-2 py-0.5 text-[11px] font-semibold text-risk-green ring-1 ring-risk-green/40">Real</span>
        </div>
        <p className="mb-4 text-xs text-slate-400">
          Forecasts on the monthly RTT waiting list (published since 2007) and three years of
          provider-level A&E activity. Monthly grain, because that is the grain NHS England publishes.
        </p>
        <RealForecastPanel />
      </GlassCard>

      <div className="mb-3 mt-8 flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-white">Daily projections — modelled series</h3>
        <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] font-semibold text-slate-300 ring-1 ring-white/15">Modelled</span>
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-2">
          {TARGETS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTarget(t.id)}
              className={clsx(
                "rounded-xl px-4 py-2 text-sm font-medium transition-all ring-1",
                target === t.id
                  ? "bg-nhs-cyan/15 text-nhs-cyan ring-nhs-cyan/40 shadow-glow"
                  : "bg-white/[0.03] text-slate-400 ring-white/10 hover:text-white"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-1 rounded-xl bg-white/[0.03] p-1 ring-1 ring-white/10">
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              className={clsx(
                "rounded-lg px-3 py-1.5 text-sm font-medium transition-all",
                horizon === h ? "bg-nhs-blue text-white" : "text-slate-400 hover:text-white"
              )}
            >
              {h}d
            </button>
          ))}
        </div>
      </div>

      <GlassCard>
        <h3 className="mb-3 font-semibold text-white">
          {TARGETS.find((t) => t.id === target)?.label} · {horizon}-day forecast (national mean)
        </h3>
        {q.isLoading ? (
          <Skeleton className="h-80" />
        ) : data.length === 0 ? (
          <div className="grid h-80 place-items-center text-slate-500">No forecast rows for this selection.</div>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={data} margin={{ left: -12, right: 8, top: 8 }}>
              <defs>
                <linearGradient id="bandgrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00C2D1" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#00C2D1" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="date_key" tick={{ fill: "#94a3b8", fontSize: 11 }} minTickGap={40} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip content={chartTooltip} />
              <Area type="monotone" dataKey="band" name="80% conformal band" stroke="none" fill="url(#bandgrad)" />
              <Line type="monotone" dataKey="yhat" name="Forecast" stroke="#00C2D1" strokeWidth={2.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
        <p className="mt-2 text-xs text-slate-500">
          The daily series is modelled: NHS England publishes monthly, so anything at daily
          resolution is a simulation layered on the real trust roster. Accuracy for these models
          is reported on the Evidence page against trivial baselines.
        </p>
      </GlassCard>
    </div>
  );
}
