import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BedDouble, Clock, Database, Stethoscope, TriangleAlert, Users2, type LucideIcon } from "lucide-react";
import {
  useKpis, useNhsAe, useNhsRtt, usePressure, useProviderRisk, useRiskDistribution, useRiskTop, useRttHistory,
} from "../lib/api";
import {
  AnimatedNumber, EmptyState, GlassCard, ProvenanceTag, RiskPill, SectionHeading, SectionTitle, Skeleton,
} from "../components/ui";
import { AXIS, ChartFrame, CROSSHAIR, GRID, SERIES, TICK, chartTooltip, fmtNumber } from "../components/chart";
import OpsPanel from "../components/OpsPanel";

const monthLabel = (period: string) => {
  const [y, m] = period.split("-").map(Number);
  return new Date(y, m - 1).toLocaleString("en-GB", { month: "long", year: "numeric" });
};
const n = (v: number) => v.toLocaleString("en-GB");

/** A published figure. Proportional figures: this is a hero value, not a column. */
function RealTile({
  label, value, unit, sub, emphasis, delay,
}: { label: string; value: string; unit?: string; sub: string; emphasis?: boolean; delay: number }) {
  return (
    <GlassCard delay={delay} className="!p-4 ring-1 ring-risk-green/20 sm:!p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-2 font-bold text-white ${emphasis ? "text-3xl" : "text-2xl sm:text-3xl"}`}>
        {value}
        {unit && <span className="ml-0.5 text-lg font-medium text-slate-400">{unit}</span>}
      </p>
      <p className="mt-1 text-xs text-slate-400">{sub}</p>
    </GlassCard>
  );
}

function Kpi({
  icon: Icon, label, value, decimals = 0, suffix = "", delay,
}: { icon: LucideIcon; label: string; value: number; decimals?: number; suffix?: string; delay: number }) {
  return (
    <GlassCard delay={delay} className="relative overflow-hidden !p-4 sm:!p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
          <p className="mt-2 text-3xl font-bold text-white">
            <AnimatedNumber value={value} decimals={decimals} />
            <span className="ml-0.5 text-lg font-medium text-slate-400">{suffix}</span>
          </p>
        </div>
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-nhs-cyan/10 text-nhs-cyan ring-1 ring-nhs-cyan/20">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      </div>
    </GlassCard>
  );
}

/** One series, one axis. Two of these side by side replace a dual-axis chart. */
function SmallMultiple({
  title, data, dataKey, xKey, color, unit, id, tickFmt,
}: {
  title: string; data: object[]; dataKey: string; xKey: string; color: string; unit: string; id: string;
  tickFmt?: (v: unknown) => string;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-300">{title}</p>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.18} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey={xKey} tick={TICK} minTickGap={48} axisLine={{ stroke: AXIS }} tickLine={false}
                 tickFormatter={tickFmt ?? ((v) => String(v).slice(5, 10))} />
          <YAxis tick={TICK} axisLine={false} tickLine={false} width={52} domain={["auto", "auto"]}
                 tickFormatter={(v) => (unit === "%" ? `${Number(v).toFixed(1)}%` : fmtNumber(Number(v), 0))} />
          <Tooltip content={chartTooltip} cursor={CROSSHAIR} />
          <Area type="monotone" dataKey={dataKey} name={title} stroke={color} fill={`url(#${id})`}
                strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#0f1527" }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Overview() {
  // Published position — NHS England, monthly.
  const rtt = useNhsRtt();
  const ae = useNhsAe();
  const risk = useProviderRisk(1);
  const rttHist = useRttHistory(60);
  // Modelled daily layer.
  const kpis = useKpis();
  const pressure = usePressure(90);
  const dist = useRiskDistribution();
  const top = useRiskTop();

  const rttNow = rtt.data?.national?.[0];
  const aeNow = ae.data?.national?.[0];
  const aeSeries = [...(ae.data?.national ?? [])].reverse();
  const rttSeries = rttHist.data?.series ?? [];
  const realLoading = rtt.isLoading || ae.isLoading || risk.isLoading;
  const hasReal = Boolean(rttNow || aeNow);

  const hasError = kpis.isError || pressure.isError || dist.isError || top.isError;
  const retry = () => { void Promise.all([kpis.refetch(), pressure.refetch(), dist.refetch(), top.refetch()]); };
  const distMap = Object.fromEntries((dist.data ?? []).map((d) => [d.classification, d.n]));
  const trend = pressure.data ?? [];

  return (
    <div>
      <SectionTitle
        eyebrow="National position"
        title="Executive Overview"
        subtitle="NHS England's latest published position first; the modelled daily layer — what the platform does with a trust's own feed — beneath it."
      />

      {/* ---------------------------------------------------------------- Real */}
      <div className="mb-2 flex items-center gap-2">
        <span className="eyebrow">Published position</span>
        <ProvenanceTag kind="real" />
        {rttNow && aeNow && (
          <span className="text-xs text-slate-400">RTT {monthLabel(rttNow.period)} · A&E {monthLabel(aeNow.period)}</span>
        )}
      </div>

      {realLoading ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
      ) : !hasReal ? (
        <EmptyState icon={Database} title="Published NHS data not loaded"
                    hint={<>Run <code className="text-nhs-cyan">scripts/ingest_nhs_real.py</code> from a normal network connection.</>} />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
          {rttNow && (
            <>
              <RealTile emphasis delay={0.02} label="RTT waiting list" value={n(rttNow.total_waiting)}
                        sub="Incomplete pathways, England" />
              <RealTile delay={0.06} label="Seen within 18 weeks" value={String(rttNow.within_18_weeks_pct)} unit="%"
                        sub={`Standard is 92% · ${n(rttNow.over_18_weeks)} waiting longer`} />
              <RealTile delay={0.1} label="Waiting over a year" value={n(rttNow.over_52_weeks)}
                        sub="Pathways beyond 52 weeks" />
            </>
          )}
          {aeNow && (
            <RealTile delay={0.14} label="A&E four-hour" value={String(aeNow.four_hour_performance_pct)} unit="%"
                      sub={`Standard is 95% · ${n(aeNow.attendances)} attendances`} />
          )}
          {risk.data?.available && (
            <RealTile delay={0.18} label="Providers in Red" value={n(risk.data.summary.Red ?? 0)}
                      sub={`of ${n(risk.data.peer_count)} scored · ${n(risk.data.summary.Amber ?? 0)} Amber`} />
          )}
        </div>
      )}

      {hasReal && (
        <GlassCard className="mt-4" delay={0.12}>
          <ChartFrame
            title="Published trend"
            subtitle="Monthly A&E attendances over three years, and the RTT waiting list over five. Forecasts and their skill are on the Forecasting page."
            right={<ProvenanceTag kind="real" />}
            rows={rttSeries}
            columns={[
              { key: "period", label: "Month" },
              { key: "total_waiting", label: "RTT waiting list", align: "right" },
              { key: "within_18_weeks_pct", label: "Within 18 weeks %", align: "right" },
              { key: "over_52_weeks", label: "52+ weeks", align: "right" },
            ]}
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <SmallMultiple title="A&E attendances (monthly)" data={aeSeries} dataKey="attendances" xKey="period"
                             color={SERIES[1]} unit="" id="g-ae-real" tickFmt={(v) => String(v)} />
              <SmallMultiple title="RTT waiting list" data={rttSeries} dataKey="total_waiting" xKey="period"
                             color={SERIES[0]} unit="" id="g-rtt-real" tickFmt={(v) => String(v)} />
            </div>
          </ChartFrame>
        </GlassCard>
      )}

      {/* ------------------------------------------------------------ Modelled */}
      <div className="mb-2 mt-10 flex flex-wrap items-center gap-2">
        <span className="eyebrow">Modelled daily layer</span>
        <ProvenanceTag kind="modelled" />
        <span className="text-xs text-slate-400">
          16 trusts on the real roster, synthetic daily activity{kpis.data?.latest_date ? ` · latest ${kpis.data.latest_date}` : ""}
        </span>
      </div>

      {hasError && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-risk-red/30 bg-risk-red/10 p-4 text-sm text-white">
          <span>Live data is unavailable. The API or database may be down.</span>
          <button type="button" onClick={retry} className="rounded-lg border border-white/20 px-3 py-1.5 font-medium hover:bg-white/10">
            Try again
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
        {kpis.isLoading ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-28" />)
        ) : kpis.data ? (
          <>
            <Kpi icon={Stethoscope} label="A&E attendances / day" value={kpis.data.ae_attendances} delay={0.02} />
            <Kpi icon={BedDouble} label="Capacity pressure" value={kpis.data.avg_bed_occupancy_pct} decimals={1} suffix="%" delay={0.06} />
            <Kpi icon={Clock} label="Waiting list" value={kpis.data.total_waiting_list} delay={0.1} />
            <Kpi icon={Users2} label="Vacancy rate" value={kpis.data.avg_vacancy_rate} decimals={1} suffix="%" delay={0.14} />
            <Kpi icon={TriangleAlert} label="Trusts in red" value={kpis.data.trusts_red} delay={0.18} />
          </>
        ) : (
          <p className="col-span-full rounded-xl border border-white/10 p-4 text-sm text-slate-300">KPI data is unavailable.</p>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <GlassCard className="xl:col-span-2" delay={0.1}>
          <ChartFrame
            title="Last 90 days"
            subtitle="Capacity pressure and A&E demand, each on its own scale."
            right={<ProvenanceTag kind="modelled" />}
            rows={trend}
            columns={[
              { key: "date_key", label: "Date" },
              { key: "avg_bed_occupancy_pct", label: "Capacity pressure %", align: "right" },
              { key: "ae_attendances", label: "A&E attendances", align: "right" },
            ]}
          >
            {pressure.isLoading ? (
              <Skeleton className="h-[420px]" />
            ) : trend.length ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <SmallMultiple title="Capacity pressure" data={trend} dataKey="avg_bed_occupancy_pct" xKey="date_key" color={SERIES[0]} unit="%" id="g-occ" />
                <SmallMultiple title="A&E attendances" data={trend} dataKey="ae_attendances" xKey="date_key" color={SERIES[1]} unit="" id="g-ae" />
              </div>
            ) : (
              <p className="grid h-72 place-items-center text-sm text-slate-300">Trend data is unavailable.</p>
            )}
          </ChartFrame>
        </GlassCard>

        <GlassCard delay={0.16}>
          <SectionHeading title="Operational risk" kind="modelled">
            Composite score per trust, classified Green, Amber or Red.
          </SectionHeading>
          <div className="flex flex-col gap-3">
            {(["Red", "Amber", "Green"] as const).map((lvl) => {
              const count = distMap[lvl] ?? 0;
              const total = Object.values(distMap).reduce((a, b) => a + (b as number), 0) || 1;
              const pct = Math.round((count / total) * 100);
              const color = lvl === "Red" ? "#ef4444" : lvl === "Amber" ? "#f59e0b" : "#22c55e";
              return (
                <div key={lvl}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <RiskPill level={lvl} />
                    <span className="font-semibold text-white">{count}</span>
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

      <GlassCard className="mt-4" delay={0.2}>
        <SectionHeading title="Top at-risk trusts" kind="modelled" />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr className="border-b border-white/10">
                <th className="pb-2 font-medium">Trust</th>
                <th className="pb-2 font-medium">Region</th>
                <th className="pb-2 font-medium">Risk</th>
                <th className="pb-2 text-right font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {(top.data ?? []).map((r, i) => (
                <tr key={i} className="border-b border-white/5 transition hover:bg-white/[0.03]">
                  <td className="py-2.5 pr-4 text-slate-200">{r.hospital_name}</td>
                  <td className="py-2.5 pr-4 text-slate-400">{r.region_name}</td>
                  <td className="py-2.5"><RiskPill level={r.classification} /></td>
                  <td className="py-2.5 text-right tabular-nums text-slate-200">{r.score?.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      <div className="mt-4">
        <OpsPanel />
      </div>
    </div>
  );
}
