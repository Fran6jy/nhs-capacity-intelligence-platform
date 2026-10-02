import { Activity, Ambulance, BedDouble, Brain, Sparkles, Users, type LucideIcon } from "lucide-react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useOpsExplain, useOpsState } from "../lib/api";
import { EmptyState, GlassCard, SectionHeading, Skeleton } from "./ui";
import { AXIS, ChartLegend, CROSSHAIR, GRID, SERIES, TICK, chartTooltip } from "./chart";

/** Stat tile: the value wears text ink; the icon carries the tone. */
function Stat({ icon: Icon, label, value, tone }: { icon: LucideIcon; label: string; value: string; tone: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-400">
        <Icon className={`h-3.5 w-3.5 ${tone}`} aria-hidden /> {label}
      </div>
      <div className="mt-1 text-2xl font-bold text-white">{value}</div>
    </div>
  );
}

const hhmm = (v: unknown) => String(v).slice(11, 16);

export default function OpsPanel() {
  const { data, isLoading } = useOpsState();
  const explain = useOpsExplain();

  return (
    <GlassCard delay={0.24}>
      <SectionHeading
        title={
          <span className="inline-flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-nhs-cyan opacity-60" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-nhs-cyan" />
            </span>
            A&amp;E operations — digital twin
          </span>
        }
        kind="live"
      >
        Minute-level department state for every trust, simulated with real operational dynamics
        (winter and time-of-day demand, bed flow, bed block, staffing throughput, ambulance
        handovers). Refreshes every 15 seconds.
      </SectionHeading>

      {isLoading ? (
        <Skeleton className="h-72" />
      ) : !data?.available ? (
        <EmptyState
          icon={Activity}
          title="No live operational state"
          hint={<>Seed the digital twin with <code className="rounded bg-white/5 px-1">run_stream_sim.py</code>.</>}
        />
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat icon={BedDouble} label="Mean occupancy" value={`${data.latest.occupancy_pct}%`} tone="text-nhs-cyan" />
            <Stat icon={Activity} label="Beds available" value={data.latest.available_beds.toLocaleString("en-GB")} tone="text-risk-green" />
            <Stat icon={Users} label="Patients queued" value={data.latest.queue_length.toLocaleString("en-GB")} tone="text-risk-amber" />
            <Stat icon={Ambulance} label="Ambulances waiting" value={data.latest.ambulances_waiting.toLocaleString("en-GB")} tone="text-risk-red" />
          </div>

          {/* Two charts, two units. Occupancy is a percentage; queue and
              ambulances are counts of the same kind, so those share one axis. */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-medium text-slate-300">Occupancy</p>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={data.minutes} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
                  <defs>
                    <linearGradient id="ops-occ" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={SERIES[0]} stopOpacity={0.18} />
                      <stop offset="100%" stopColor={SERIES[0]} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="minute_ts" tick={TICK} minTickGap={48} tickFormatter={hhmm} axisLine={{ stroke: AXIS }} tickLine={false} />
                  <YAxis tick={TICK} axisLine={false} tickLine={false} width={40} domain={["auto", "auto"]} tickFormatter={(v) => `${v}%`} />
                  <Tooltip content={chartTooltip} cursor={CROSSHAIR} labelFormatter={hhmm} />
                  <Area type="monotone" dataKey="occupancy_pct" name="Occupancy %" stroke={SERIES[0]} fill="url(#ops-occ)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div>
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-slate-300">Queue and handovers</p>
                <ChartLegend items={[{ name: "Patients queued", color: SERIES[1] }, { name: "Ambulances waiting", color: SERIES[2] }]} />
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={data.minutes} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="minute_ts" tick={TICK} minTickGap={48} tickFormatter={hhmm} axisLine={{ stroke: AXIS }} tickLine={false} />
                  <YAxis tick={TICK} axisLine={false} tickLine={false} width={40} />
                  <Tooltip content={chartTooltip} cursor={CROSSHAIR} labelFormatter={hhmm} />
                  <Line type="monotone" dataKey="queue_length" name="Patients queued" stroke={SERIES[1]} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="ambulances_waiting" name="Ambulances waiting" stroke={SERIES[2]} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* AI pressure copilot */}
          <div className="mt-4 rounded-xl border border-nhs-cyan/20 bg-nhs-cyan/[0.05] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Brain className="h-4 w-4 text-nhs-cyan" aria-hidden /> AI pressure copilot
              </div>
              <button
                type="button"
                onClick={() => explain.mutate()}
                disabled={explain.isPending}
                className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-nhs-blue to-nhs-cyan px-3 py-1.5 text-xs font-medium text-white shadow-glow transition disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" aria-hidden />
                {explain.isPending ? "Analysing…" : "Explain current pressure"}
              </button>
            </div>
            {explain.data && (
              <>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <Chip label="Arrivals vs baseline" value={`${explain.data.metrics.arrivals_vs_baseline_pct > 0 ? "+" : ""}${explain.data.metrics.arrivals_vs_baseline_pct}%`} />
                  <Chip label="Occupancy" value={`${explain.data.metrics.occupancy_pct}%`} />
                  <Chip label="Beds Δ" value={`${explain.data.metrics.available_beds_change > 0 ? "+" : ""}${explain.data.metrics.available_beds_change}`} />
                  <Chip label="Ambulances waiting" value={`${explain.data.metrics.ambulances_waiting_now}`} />
                </div>
                <p className="mt-3 text-sm leading-relaxed text-slate-200">{explain.data.narrative}</p>
                <p className="mt-1 text-[11px] text-slate-400">via {explain.data.provider} · explains the simulated feed above</p>
              </>
            )}
            {explain.isError && <p className="mt-2 text-sm text-risk-red" role="alert">Could not generate analysis.</p>}
          </div>
        </>
      )}
    </GlassCard>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-full bg-white/[0.06] px-2.5 py-1 ring-1 ring-white/10">
      <span className="text-slate-400">{label}:</span> <span className="font-semibold text-white">{value}</span>
    </span>
  );
}
