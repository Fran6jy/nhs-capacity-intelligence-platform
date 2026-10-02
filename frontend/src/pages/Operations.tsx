import { BedDouble, Clock, Stethoscope, TriangleAlert, Users2, type LucideIcon } from "lucide-react";
import { useKpis, usePressure, useRiskDistribution, useRiskTop } from "../lib/api";
import { AnimatedNumber, GlassCard, ProvenanceTag, RiskPill, SectionHeading, SectionTitle, Skeleton } from "../components/ui";
import { ChartFrame, SERIES, SmallMultiple } from "../components/chart";
import OpsPanel from "../components/OpsPanel";

function Kpi({
  icon: Icon, label, value, decimals = 0, suffix = "", delay,
}: { icon: LucideIcon; label: string; value: number; decimals?: number; suffix?: string; delay: number }) {
  return (
    <GlassCard delay={delay} className="relative overflow-hidden !p-4 sm:!p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
          <p className="numeral mt-3 text-3xl sm:text-4xl">
            <AnimatedNumber value={value} decimals={decimals} />
            <span className="ml-0.5 text-lg font-medium text-slate-400">{suffix}</span>
          </p>
        </div>
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 text-slate-400">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      </div>
    </GlassCard>
  );
}

/**
 * The demonstration layer.
 *
 * NHS England publishes monthly. A trust operates on daily and intraday
 * data, and that is the context this platform is built for. This page
 * simulates the feed a trust would supply — sixteen real trusts from the
 * ODS roster, synthetic daily activity, a minute-level department twin —
 * to show what the platform does at that grain. Nothing here is a
 * published figure, and nothing here sits next to one.
 */
export default function Operations() {
  const kpis = useKpis();
  const pressure = usePressure(90);
  const dist = useRiskDistribution();
  const top = useRiskTop();
  const hasError = kpis.isError || pressure.isError || dist.isError || top.isError;
  const retry = () => { void Promise.all([kpis.refetch(), pressure.refetch(), dist.refetch(), top.refetch()]); };
  const distMap = Object.fromEntries((dist.data ?? []).map((d) => [d.classification, d.n]));
  const trend = pressure.data ?? [];

  return (
    <div>
      <SectionTitle
        eyebrow="Demonstration"
        title="Daily operations"
        subtitle="NHS England publishes monthly. A trust runs on daily and intraday data. This page simulates that feed — sixteen real trusts, synthetic daily activity, a minute-level department twin — to show what the platform does with it. Nothing here is a published figure."
      />

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="eyebrow">Daily indicators</span>
        <ProvenanceTag kind="modelled" />
        {kpis.data?.latest_date && <span className="text-xs text-slate-400">latest {kpis.data.latest_date}</span>}
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
