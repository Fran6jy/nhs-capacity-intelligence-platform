import { Link } from "react-router-dom";
import { ArrowRight, Database, Radio } from "lucide-react";
import { useNhsAe, useNhsForecastMetrics, useNhsRtt, useProviderRisk, useRttHistory } from "../lib/api";
import { EmptyState, GlassCard, ProvenanceTag, SectionTitle, Skeleton } from "../components/ui";
import { ChartFrame, SERIES, SmallMultiple } from "../components/chart";

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

/**
 * The Executive Overview carries NHS England's published position and
 * nothing else. The modelled daily layer — what the platform does with a
 * trust's own feed — lives on its own page, so no simulated figure ever
 * sits beside a real one.
 */
export default function Overview() {
  const rtt = useNhsRtt();
  const ae = useNhsAe();
  const risk = useProviderRisk(1);
  const rttHist = useRttHistory(60);
  const metrics = useNhsForecastMetrics();

  const rttNow = rtt.data?.national?.[0];
  const aeNow = ae.data?.national?.[0];
  const aeSeries = [...(ae.data?.national ?? [])].reverse();
  const rttSeries = rttHist.data?.series ?? [];
  const loading = rtt.isLoading || ae.isLoading || risk.isLoading;
  const hasReal = Boolean(rttNow || aeNow);
  const bestSkill = metrics.data?.metrics?.length
    ? Math.max(...metrics.data.metrics.map((m) => m.skill))
    : null;

  return (
    <div>
      <SectionTitle
        eyebrow="National position"
        title="Executive Overview"
        subtitle="NHS England's latest published position. Every figure on this page is a published number; the month and the standard it is measured against are stated on each tile."
      />

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="eyebrow">Published position</span>
        <ProvenanceTag kind="real" />
        {rttNow && aeNow && (
          <span className="text-xs text-slate-400">RTT {monthLabel(rttNow.period)} · A&E {monthLabel(aeNow.period)}</span>
        )}
      </div>

      {loading ? (
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
            subtitle="Monthly A&E attendances over three years, and the RTT waiting list over five."
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

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Link to="/forecasting" className="group glass glass-hover block p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow mb-1">Twelve-month outlook</p>
              <p className="font-semibold text-white">Forecasts on these series, with their skill</p>
              <p className="mt-1 text-xs text-slate-400">
                {bestSkill != null
                  ? `Best model removes ${Math.round(bestSkill * 100)}% of the error of "same month last year".`
                  : "Each forecast is back-tested against a trivial baseline and named."}
              </p>
            </div>
            <ArrowRight className="h-5 w-5 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-white" aria-hidden />
          </div>
        </Link>
        <Link to="/operations" className="group glass glass-hover block p-5 sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow mb-1 flex items-center gap-1.5"><Radio className="h-3 w-3" aria-hidden /> Demonstration</p>
              <p className="font-semibold text-white">What the platform does with a trust's daily feed</p>
              <p className="mt-1 text-xs text-slate-400">
                NHS England publishes monthly. The daily layer, the risk engine and the live department twin run on a simulated feed, kept apart from the figures above.
              </p>
            </div>
            <ArrowRight className="h-5 w-5 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-white" aria-hidden />
          </div>
        </Link>
      </div>
    </div>
  );
}
