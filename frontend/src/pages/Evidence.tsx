import { motion } from "framer-motion";
import { CheckCircle2, Database, FlaskConical, ShieldCheck, Target } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useForecastActual,
  useNhsAe,
  useNhsRtt,
  useValidationMetrics,
  useValidationSources,
} from "../lib/api";
import { GlassCard, SectionTitle, Skeleton } from "../components/ui";
import { chartTooltip } from "../components/chart";

function accentFor(a: number) {
  if (a >= 85) return { ring: "ring-risk-green/40", text: "text-risk-green", bar: "#22c55e" };
  if (a >= 70) return { ring: "ring-risk-amber/40", text: "text-risk-amber", bar: "#f59e0b" };
  return { ring: "ring-risk-red/40", text: "text-risk-red", bar: "#ef4444" };
}

const MONTH_LABEL = (period: string) => {
  const [y, m] = period.split("-").map(Number);
  return new Date(y, m - 1).toLocaleString("en-GB", { month: "long", year: "numeric" });
};

const compact = (n: number) => n.toLocaleString("en-GB");

/** One published figure, with the period it was published for. */
function RealStat({
  label, value, unit, sub, emphasis,
}: { label: string; value: string; unit?: string; sub: string; emphasis?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 ring-1 ring-risk-green/20">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1.5 font-bold tabular-nums ${emphasis ? "text-3xl text-white" : "text-2xl text-slate-100"}`}>
        {value}
        {unit && <span className="ml-1 text-base font-medium text-slate-400">{unit}</span>}
      </div>
      <div className="mt-1 text-xs text-slate-400">{sub}</div>
    </div>
  );
}

export default function Evidence() {
  const sources = useValidationSources();
  const metrics = useValidationMetrics();
  const fa = useForecastActual();
  const rtt = useNhsRtt();
  const ae = useNhsAe();

  const rttNow = rtt.data?.national?.[0];
  const aeNow = ae.data?.national?.[0];
  const aeTrend = [...(ae.data?.national ?? [])].reverse();
  // Worst-performing region first — the one a reader is looking for.
  const regionsByPerformance = [...(ae.data?.by_region ?? [])].sort(
    (a, b) => a.four_hour_performance_pct - b.four_hour_performance_pct,
  );
  const hasReal = Boolean(rttNow || aeNow);

  return (
    <div>
      <SectionTitle
        title="Evidence & Validation"
        subtitle="How do we know it works? Real data provenance + back-tested model accuracy."
      />

      {/* Published NHS England statistics — the real figures, stated first */}
      <GlassCard delay={0.02}>
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-risk-green" />
          <h3 className="font-semibold text-white">Published NHS England statistics</h3>
          <span className="rounded-full bg-risk-green/15 px-2 py-0.5 text-[11px] font-semibold text-risk-green ring-1 ring-risk-green/40">
            Real
          </span>
        </div>
        <p className="mb-4 text-xs text-slate-400">
          Ingested directly from NHS England's monthly open data releases — not modelled, not
          simulated. These are the same numbers quoted in the national press.
        </p>

        {rtt.isLoading || ae.isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
          </div>
        ) : !hasReal ? (
          <p className="text-sm text-slate-400">
            Real NHS data not loaded yet — run <code className="text-nhs-cyan">scripts/ingest_nhs_real.py</code>.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {rttNow && (
                <>
                  <RealStat
                    emphasis
                    label="RTT waiting list"
                    value={compact(rttNow.total_waiting)}
                    sub={`Incomplete pathways · ${MONTH_LABEL(rttNow.period)}`}
                  />
                  <RealStat
                    label="Seen within 18 weeks"
                    value={String(rttNow.within_18_weeks_pct)}
                    unit="%"
                    sub={`Against the 92% standard · ${compact(rttNow.over_18_weeks)} over`}
                  />
                  <RealStat
                    label="Waiting 52+ weeks"
                    value={compact(rttNow.over_52_weeks)}
                    sub="Patients waiting over a year"
                  />
                </>
              )}
              {aeNow && (
                <RealStat
                  label="A&E four-hour performance"
                  value={String(aeNow.four_hour_performance_pct)}
                  unit="%"
                  sub={`${compact(aeNow.attendances)} attendances · ${MONTH_LABEL(aeNow.period)}`}
                />
              )}
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* Waiting list by specialty */}
              {rtt.data?.by_specialty?.length ? (
                <div>
                  <h4 className="mb-2 text-sm font-medium text-slate-200">
                    Largest waiting lists by specialty
                  </h4>
                  <div className="overflow-hidden rounded-xl border border-white/10">
                    <table className="w-full text-sm">
                      <thead className="bg-white/[0.04] text-xs uppercase tracking-wide text-slate-400">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">Specialty</th>
                          <th className="px-3 py-2 text-right font-medium">Waiting</th>
                          <th className="px-3 py-2 text-right font-medium">Median</th>
                          <th className="px-3 py-2 text-right font-medium">52w+</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {rtt.data.by_specialty.map((s) => (
                          <tr key={s.specialty_name} className="text-slate-300">
                            <td className="px-3 py-2">{s.specialty_name.replace(" Service", "")}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{compact(s.total_waiting)}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-slate-400">
                              {s.median_wait_weeks}w
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-risk-amber">
                              {compact(s.over_52_weeks)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

              {/* Regional A&E performance */}
              {ae.data?.by_region?.length ? (
                <div>
                  <h4 className="mb-2 text-sm font-medium text-slate-200">
                    A&E four-hour performance by region
                  </h4>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart
                      data={regionsByPerformance}
                      layout="vertical"
                      margin={{ left: 8, right: 16, top: 4 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                      <XAxis type="number" domain={[60, 85]} tick={{ fill: "#94a3b8", fontSize: 11 }}
                             tickFormatter={(v) => `${v}%`} />
                      <YAxis type="category" dataKey="region_name" width={104}
                             tick={{ fill: "#94a3b8", fontSize: 10 }}
                             tickFormatter={(v) => String(v).replace("NHS ENGLAND ", "")} />
                      <Tooltip content={chartTooltip} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                      {/* barSize is explicit: in a vertical layout Recharts derives a
                          zero height here and the bars render as flat lines. */}
                      <Bar dataKey="four_hour_performance_pct" name="Within 4 hours"
                           barSize={18} radius={[0, 4, 4, 0]}>
                        {regionsByPerformance.map((r) => (
                          <Cell
                            key={r.region_name}
                            fill={r.four_hour_performance_pct >= 76 ? "#22c55e" : "#f59e0b"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : null}
            </div>

            {aeTrend.length > 1 && (
              <p className="mt-4 text-xs text-slate-500">
                A&E attendances over the last {aeTrend.length} published months:{" "}
                {aeTrend.map((m, i) => (
                  <span key={m.period}>
                    {i > 0 && " → "}
                    <span className="text-slate-300">
                      {MONTH_LABEL(m.period).split(" ")[0]} {compact(m.attendances)}
                    </span>
                  </span>
                ))}
                . The 92% RTT and 95% A&E standards have not been met nationally for years; these are
                the published figures, not a target-adjusted view.
              </p>
            )}
          </>
        )}
      </GlassCard>

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
          RTT waiting lists, A&E activity, the trust roster and weather are real published sources.
          Daily and minute-level figures are modelled — NHS England publishes monthly, so anything
          finer is necessarily a behavioural digital twin layered on the real roster.
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
