import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ClipboardList } from "lucide-react";
import { useRecommendations, useWorkforce } from "../lib/api";
import { EmptyState, GlassCard, SectionHeading, SectionTitle, Skeleton } from "../components/ui";
import { AXIS, BAR_CURSOR, ChartFrame, GRID, TICK, chartTooltip } from "../components/chart";

const sevColor: Record<string, string> = { High: "#ef4444", Medium: "#f59e0b", Low: "#22c55e" };

// Status thresholds, not a value ramp: colour here *means* something
// (chronic understaffing), so the status palette is the right one and the
// legend states the rule so it is never colour alone.
const barColor = (v: number) => (v >= 12 ? "#ef4444" : v >= 8 ? "#f59e0b" : "#22c55e");

export default function Workforce() {
  const wf = useWorkforce();
  const recs = useRecommendations();

  const data = (wf.data ?? [])
    .slice()
    .sort((a, b) => b.vacancy_rate - a.vacancy_rate)
    .slice(0, 12)
    .map((w) => ({ ...w, short: w.hospital_name.replace(/ NHS.*$/, "") }));

  return (
    <div>
      <SectionTitle
        eyebrow="Staffing"
        title="Workforce"
        subtitle="Vacancy pressure by trust, and the rule-based actions it triggers. Modelled staffing on the real trust roster."
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <GlassCard className="xl:col-span-3">
          <ChartFrame
            title="Vacancy rate by trust"
            subtitle="Twelve highest. Colour marks the threshold band: ≥12% chronic, ≥8% elevated, otherwise within range."
            legend={[
              { name: "≥ 12% chronic", color: "#ef4444", kind: "bar" },
              { name: "≥ 8% elevated", color: "#f59e0b", kind: "bar" },
              { name: "< 8%", color: "#22c55e", kind: "bar" },
            ]}
            rows={data}
            columns={[
              { key: "hospital_name", label: "Trust" },
              { key: "region_id", label: "Region" },
              { key: "staff_count", label: "Staff", align: "right" },
              { key: "vacancies", label: "Vacancies", align: "right" },
              { key: "vacancy_rate", label: "Vacancy %", align: "right", format: (v) => `${Number(v).toFixed(1)}%` },
            ]}
          >
            {wf.isLoading ? (
              <Skeleton className="h-96" />
            ) : data.length === 0 ? (
              <EmptyState icon={ClipboardList} title="No workforce data" hint="Run the pipeline to populate staffing." />
            ) : (
              <ResponsiveContainer width="100%" height={420}>
                <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }} barCategoryGap={6}>
                  <CartesianGrid stroke={GRID} horizontal={false} />
                  <XAxis type="number" tick={TICK} axisLine={{ stroke: AXIS }} tickLine={false} tickFormatter={(v) => `${v}%`} />
                  <YAxis type="category" dataKey="short" tick={{ fill: "#cbd5e1", fontSize: 11 }} width={160} axisLine={false} tickLine={false} />
                  <Tooltip content={chartTooltip} cursor={BAR_CURSOR} />
                  <Bar dataKey="vacancy_rate" name="Vacancy %" barSize={18} radius={[0, 4, 4, 0]}>
                    {data.map((d, i) => (
                      <Cell key={i} fill={barColor(d.vacancy_rate)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartFrame>
        </GlassCard>

        <GlassCard className="xl:col-span-2">
          <SectionHeading title="Recommended actions" kind="modelled">
            Each action states the figure that triggered it and the threshold it crossed. No effect
            sizes are claimed, because none of these rules is backed by an intervention study.
          </SectionHeading>
          <div className="flex max-h-[460px] flex-col gap-3 overflow-y-auto pr-1">
            {recs.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20" />)
            ) : (recs.data ?? []).length === 0 ? (
              <EmptyState icon={ClipboardList} title="No actions triggered" hint="No trust is currently Amber or Red." />
            ) : (
              (recs.data ?? []).map((r) => (
                <article key={r.recommendation_id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                      style={{ background: `${sevColor[r.severity] ?? "#64748b"}22`, color: sevColor[r.severity] ?? "#94a3b8" }}
                    >
                      {r.severity} · {r.category}
                    </span>
                    <span className="truncate text-xs text-slate-400">{r.hospital_name}</span>
                  </div>
                  <p className="text-sm leading-relaxed text-slate-200">{r.action}</p>
                  {r.expected_impact && <p className="mt-1 text-xs text-nhs-cyan">→ {r.expected_impact}</p>}
                </article>
              ))
            )}
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
