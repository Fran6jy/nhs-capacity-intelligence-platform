import { useState } from "react";
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
import { useForecasts } from "../lib/api";
import { GlassCard, SectionTitle, Skeleton } from "../components/ui";
import { chartTooltip } from "../components/chart";
import clsx from "clsx";

const TARGETS = [
  { id: "bed_occupancy", label: "Bed occupancy" },
  { id: "ae_demand", label: "A&E demand" },
  { id: "waiting_time", label: "Waiting time" },
  { id: "workforce_demand", label: "Workforce" },
];
const HORIZONS = [30, 60, 90];

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
      <SectionTitle title="Forecasting" subtitle="30/60/90-day projections — Prophet · XGBoost · LightGBM" />

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
              <Area type="monotone" dataKey="band" name="Confidence band" stroke="none" fill="url(#bandgrad)" />
              <Line type="monotone" dataKey="yhat" name="Forecast" stroke="#00C2D1" strokeWidth={2.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </GlassCard>
    </div>
  );
}
