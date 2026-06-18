import { Activity, Ambulance, Radio, TriangleAlert } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useStreamAe } from "../lib/api";
import { GlassCard, Skeleton } from "./ui";
import { chartTooltip } from "./chart";

function pct(n: number, d: number) {
  return d ? Math.round((n / d) * 100) : 0;
}

export default function StreamPanel() {
  const { data, isLoading } = useStreamAe();

  return (
    <GlassCard delay={0.24}>
      <div className="mb-4 flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-risk-red opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-risk-red" />
        </span>
        <h3 className="font-semibold text-white">Live A&amp;E pressure</h3>
        <span className="text-xs text-slate-500">real-time stream · refreshes every 15s</span>
      </div>

      {isLoading ? (
        <Skeleton className="h-64" />
      ) : !data?.available || data.minutes.length === 0 ? (
        <div className="grid h-48 place-items-center text-center text-sm text-slate-400">
          <div>
            <Radio className="mx-auto mb-2 h-6 w-6 text-slate-500" />
            No live stream data yet.
            <div className="mt-1 text-xs text-slate-500">
              Run <code className="rounded bg-white/5 px-1">python scripts/run_stream_sim.py</code> then publish to Postgres.
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat icon={Activity} label="Attendances (60m)" value={data.totals.attendances.toLocaleString()} tone="text-nhs-cyan" />
            <Stat icon={Ambulance} label="Ambulance" value={`${pct(data.totals.ambulance, data.totals.attendances)}%`} tone="text-sky-300" />
            <Stat icon={TriangleAlert} label="4h breach risk" value={`${pct(data.totals.breach_risk, data.totals.attendances)}%`} tone="text-risk-amber" />
            <Stat icon={Radio} label="Minutes streamed" value={data.minutes.length.toString()} tone="text-slate-200" />
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={data.minutes} margin={{ left: -16, right: 8, top: 8 }}>
              <defs>
                <linearGradient id="stream" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis
                dataKey="minute_ts"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                minTickGap={40}
                tickFormatter={(v) => String(v).slice(11, 16)}
              />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip content={chartTooltip} />
              <Area type="monotone" dataKey="attendances" name="Arrivals/min" stroke="#ef4444" fill="url(#stream)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </GlassCard>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-400">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className={`mt-1 text-xl font-bold ${tone}`}>{value}</div>
    </div>
  );
}
