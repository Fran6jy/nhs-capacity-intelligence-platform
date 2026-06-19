import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BedDouble, Clock, Stethoscope, TriangleAlert, Users2 } from "lucide-react";
import { useKpis, usePressure, useRiskDistribution, useRiskTop } from "../lib/api";
import { AnimatedNumber, GlassCard, RiskPill, SectionTitle, Skeleton } from "../components/ui";
import { chartTooltip } from "../components/chart";
import OpsPanel from "../components/OpsPanel";

function Kpi({
  icon: Icon,
  label,
  value,
  decimals = 0,
  suffix = "",
  delay,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
  decimals?: number;
  suffix?: string;
  delay: number;
}) {
  return (
    <GlassCard delay={delay} className="relative overflow-hidden">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
          <p className="mt-2 text-3xl font-bold text-white">
            <AnimatedNumber value={value} decimals={decimals} />
            <span className="text-lg text-slate-400">{suffix}</span>
          </p>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-nhs-cyan/10 text-nhs-cyan ring-1 ring-nhs-cyan/20">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </GlassCard>
  );
}

export default function Overview() {
  const kpis = useKpis();
  const pressure = usePressure(90);
  const dist = useRiskDistribution();
  const top = useRiskTop();

  const distMap = Object.fromEntries((dist.data ?? []).map((d) => [d.classification, d.n]));

  return (
    <div>
      <SectionTitle
        title="Executive Overview"
        subtitle={`National operational pressure${kpis.data?.latest_date ? ` · latest ${kpis.data.latest_date}` : ""}`}
      />

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {kpis.isLoading || !kpis.data ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-28" />)
        ) : (
          <>
            <Kpi icon={Stethoscope} label="A&E attendances" value={kpis.data.ae_attendances} delay={0.02} />
            <Kpi icon={BedDouble} label="Bed occupancy" value={kpis.data.avg_bed_occupancy_pct} decimals={1} suffix="%" delay={0.06} />
            <Kpi icon={Clock} label="Waiting list" value={kpis.data.total_waiting_list} delay={0.1} />
            <Kpi icon={Users2} label="Vacancy rate" value={kpis.data.avg_vacancy_rate} decimals={1} suffix="%" delay={0.14} />
            <Kpi icon={TriangleAlert} label="Trusts in red" value={kpis.data.trusts_red} delay={0.18} />
          </>
        )}
      </div>

      {/* Trend + risk distribution */}
      <div className="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="xl:col-span-2" delay={0.1}>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold text-white">Bed occupancy & A&E demand — 90 days</h3>
          </div>
          {pressure.isLoading || !pressure.data ? (
            <Skeleton className="h-72" />
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={pressure.data} margin={{ left: -16, right: 8, top: 8 }}>
                <defs>
                  <linearGradient id="occ" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00C2D1" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#00C2D1" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="ae" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0072CE" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#0072CE" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date_key" tick={{ fill: "#94a3b8", fontSize: 11 }} minTickGap={40} />
                <YAxis yAxisId="l" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <YAxis yAxisId="r" orientation="right" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip content={chartTooltip} />
                <Area yAxisId="l" type="monotone" dataKey="avg_bed_occupancy_pct" name="Bed occupancy %" stroke="#00C2D1" fill="url(#occ)" strokeWidth={2} />
                <Area yAxisId="r" type="monotone" dataKey="ae_attendances" name="A&E attendances" stroke="#0072CE" fill="url(#ae)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </GlassCard>

        <GlassCard delay={0.16}>
          <h3 className="mb-4 font-semibold text-white">Operational risk</h3>
          <div className="flex flex-col gap-3">
            {(["Red", "Amber", "Green"] as const).map((lvl) => {
              const n = distMap[lvl] ?? 0;
              const total = Object.values(distMap).reduce((a, b) => a + (b as number), 0) || 1;
              const pct = Math.round((n / total) * 100);
              const color = lvl === "Red" ? "#ef4444" : lvl === "Amber" ? "#f59e0b" : "#22c55e";
              return (
                <div key={lvl}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <RiskPill level={lvl} />
                    <span className="font-semibold text-white">{n}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-white/5">
                    <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: color }} />
                  </div>
                </div>
              );
            })}
          </div>
        </GlassCard>
      </div>

      {/* Top risk trusts */}
      <GlassCard className="mt-6" delay={0.2}>
        <h3 className="mb-4 font-semibold text-white">Top at-risk trusts</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr className="border-b border-white/10">
                <th className="pb-2">Trust</th>
                <th className="pb-2">Region</th>
                <th className="pb-2">Risk</th>
                <th className="pb-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {(top.data ?? []).map((r, i) => (
                <tr key={i} className="border-b border-white/5 hover:bg-white/[0.03]">
                  <td className="py-2.5 pr-4 text-slate-200">{r.hospital_name}</td>
                  <td className="py-2.5 pr-4 text-slate-400">{r.region_name}</td>
                  <td className="py-2.5"><RiskPill level={r.classification} /></td>
                  <td className="py-2.5 text-right font-mono text-slate-200">{r.score?.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      <div className="mt-6">
        <OpsPanel />
      </div>
    </div>
  );
}
