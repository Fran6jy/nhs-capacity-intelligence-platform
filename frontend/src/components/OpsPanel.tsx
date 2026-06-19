import { Activity, Ambulance, BedDouble, Brain, Sparkles, Users } from "lucide-react";
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
import { useOpsExplain, useOpsState } from "../lib/api";
import { GlassCard, Skeleton } from "./ui";
import { chartTooltip } from "./chart";

function Stat({ icon: Icon, label, value, tone }: {
  icon: React.ElementType; label: string; value: string; tone: string;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-400"><Icon className="h-3.5 w-3.5" /> {label}</div>
      <div className={`mt-1 text-2xl font-bold ${tone}`}>{value}</div>
    </div>
  );
}

export default function OpsPanel() {
  const { data, isLoading } = useOpsState();
  const explain = useOpsExplain();

  return (
    <GlassCard delay={0.24}>
      <div className="mb-4 flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-risk-red opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-risk-red" />
        </span>
        <h3 className="font-semibold text-white">Live A&amp;E operations — digital twin</h3>
        <span className="text-xs text-slate-500">simulated ECDS feed · refreshes every 15s</span>
      </div>

      {isLoading ? (
        <Skeleton className="h-72" />
      ) : !data?.available ? (
        <div className="grid h-40 place-items-center text-sm text-slate-400">
          No live operational state — seed the digital twin (<code className="rounded bg-white/5 px-1">run_stream_sim.py</code>).
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat icon={BedDouble} label="Mean occupancy" value={`${data.latest.occupancy_pct}%`} tone="text-nhs-cyan" />
            <Stat icon={Activity} label="Beds available" value={data.latest.available_beds.toLocaleString()} tone="text-emerald-300" />
            <Stat icon={Users} label="Patients queued" value={data.latest.queue_length.toLocaleString()} tone="text-risk-amber" />
            <Stat icon={Ambulance} label="Ambulances waiting" value={data.latest.ambulances_waiting.toLocaleString()} tone="text-risk-red" />
          </div>

          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={data.minutes} margin={{ left: -14, right: 8, top: 8 }}>
              <defs>
                <linearGradient id="occ2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00C2D1" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#00C2D1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="minute_ts" tick={{ fill: "#94a3b8", fontSize: 11 }} minTickGap={48}
                     tickFormatter={(v) => String(v).slice(11, 16)} />
              <YAxis yAxisId="l" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis yAxisId="r" orientation="right" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip content={chartTooltip} />
              <Area yAxisId="l" type="monotone" dataKey="occupancy_pct" name="Occupancy %" stroke="#00C2D1" fill="url(#occ2)" strokeWidth={2} />
              <Line yAxisId="r" type="monotone" dataKey="queue_length" name="Queue" stroke="#f59e0b" strokeWidth={2} dot={false} />
              <Line yAxisId="r" type="monotone" dataKey="ambulances_waiting" name="Ambulances" stroke="#ef4444" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>

          {/* AI pressure copilot */}
          <div className="mt-4 rounded-xl border border-nhs-cyan/20 bg-nhs-cyan/[0.05] p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <Brain className="h-4 w-4 text-nhs-cyan" /> AI pressure copilot
              </div>
              <button
                onClick={() => explain.mutate()}
                disabled={explain.isPending}
                className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-nhs-blue to-nhs-cyan px-3 py-1.5 text-xs font-medium text-white shadow-glow transition disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" />
                {explain.isPending ? "Analysing…" : "Why is pressure rising?"}
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
                <p className="mt-1 text-[11px] text-slate-500">via {explain.data.provider}</p>
              </>
            )}
            {explain.isError && <p className="mt-2 text-sm text-risk-red">Could not generate analysis.</p>}
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
