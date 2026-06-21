import { motion } from "framer-motion";
import { CheckCircle2, Database, FlaskConical, Target } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useForecastActual, useValidationMetrics, useValidationSources } from "../lib/api";
import { GlassCard, SectionTitle, Skeleton } from "../components/ui";
import { chartTooltip } from "../components/chart";

function accentFor(a: number) {
  if (a >= 85) return { ring: "ring-risk-green/40", text: "text-risk-green", bar: "#22c55e" };
  if (a >= 70) return { ring: "ring-risk-amber/40", text: "text-risk-amber", bar: "#f59e0b" };
  return { ring: "ring-risk-red/40", text: "text-risk-red", bar: "#ef4444" };
}

export default function Evidence() {
  const sources = useValidationSources();
  const metrics = useValidationMetrics();
  const fa = useForecastActual();

  return (
    <div>
      <SectionTitle
        title="Evidence & Validation"
        subtitle="How do we know it works? Real data provenance + back-tested model accuracy."
      />

      {/* Data sources */}
      <GlassCard delay={0.04}>
        <div className="mb-4 flex items-center gap-2">
          <Database className="h-4 w-4 text-nhs-cyan" />
          <h3 className="font-semibold text-white">Data sources</h3>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(sources.data ?? []).map((s) => (
            <div key={s.name} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs uppercase tracking-wide text-slate-400">{s.category}</span>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${
                  s.kind === "real" ? "bg-risk-green/15 text-risk-green ring-risk-green/40"
                                    : "bg-white/5 text-slate-300 ring-white/15"}`}>
                  {s.kind === "real" ? "Live / real" : "Modelled"}
                </span>
              </div>
              <div className="text-sm font-medium text-white">{s.name}</div>
              <div className="mt-1 text-xs text-slate-400">{s.detail}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Trust roster and weather are live external sources; operational demand is a behavioural
          digital twin, layered on the real roster.
        </p>
      </GlassCard>

      {/* Model accuracy */}
      <GlassCard className="mt-6" delay={0.1}>
        <div className="mb-4 flex items-center gap-2">
          <Target className="h-4 w-4 text-nhs-cyan" />
          <h3 className="font-semibold text-white">Model accuracy — back-tested</h3>
          <span className="text-xs text-slate-500">30-day hold-out · accuracy = 100 − MAPE</span>
        </div>
        {metrics.isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div>
        ) : !metrics.data?.available || metrics.data.metrics.length === 0 ? (
          <p className="text-sm text-slate-400">No validation yet — run the pipeline to back-test the models.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {metrics.data.metrics.map((m, i) => {
              const c = accentFor(m.accuracy);
              return (
                <motion.div key={m.target} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06 }}
                  className={`rounded-2xl border border-white/10 bg-white/[0.03] p-4 ring-1 ${c.ring}`}>
                  <div className="flex items-center gap-1.5 text-sm text-slate-300">
                    <FlaskConical className="h-3.5 w-3.5" /> {m.target}
                  </div>
                  <div className={`mt-2 text-4xl font-bold ${c.text}`}>{m.accuracy}%</div>
                  <div className="mt-1 text-xs text-slate-400">
                    {m.model} · MAPE {m.mape}% · MAE {m.mae} · n={m.n_eval.toLocaleString()}
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/5">
                    <div className="h-full rounded-full" style={{ width: `${m.accuracy}%`, background: c.bar }} />
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </GlassCard>

      {/* Forecast vs actual */}
      <GlassCard className="mt-6" delay={0.16}>
        <div className="mb-3 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-nhs-cyan" />
          <h3 className="font-semibold text-white">Forecast vs actual — capacity pressure (hold-out)</h3>
        </div>
        {fa.isLoading ? (
          <Skeleton className="h-72" />
        ) : !fa.data?.available || fa.data.series.length === 0 ? (
          <p className="text-sm text-slate-400">No back-test series available yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={fa.data.series} margin={{ left: -12, right: 8, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 11 }} minTickGap={40}
                     tickFormatter={(v) => String(v).slice(5, 10)} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} domain={["auto", "auto"]} />
              <Tooltip content={chartTooltip} />
              <Line type="monotone" dataKey="actual" name="Actual" stroke="#94a3b8" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="predicted" name="Predicted" stroke="#00C2D1" strokeWidth={2.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
        <p className="mt-2 text-xs text-slate-500">
          The model is trained on data up to the hold-out window, then predicts it blind — the
          predicted line never saw these actuals.
        </p>
      </GlassCard>
    </div>
  );
}
