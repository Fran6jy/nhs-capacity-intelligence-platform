import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useRecommendations, useWorkforce } from "../lib/api";
import { GlassCard, SectionTitle, Skeleton } from "../components/ui";
import { chartTooltip } from "../components/chart";

const sevColor: Record<string, string> = { High: "#ef4444", Medium: "#f59e0b", Low: "#22c55e" };

export default function Workforce() {
  const wf = useWorkforce();
  const recs = useRecommendations();

  const data = (wf.data ?? [])
    .slice()
    .sort((a, b) => b.vacancy_rate - a.vacancy_rate)
    .slice(0, 12)
    .map((w) => ({ ...w, short: w.hospital_name.replace(/ NHS.*$/, "") }));

  const barColor = (v: number) => (v >= 12 ? "#ef4444" : v >= 8 ? "#f59e0b" : "#22c55e");

  return (
    <div>
      <SectionTitle title="Workforce Analytics" subtitle="Staffing gaps & prescriptive actions by trust" />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <GlassCard className="xl:col-span-3">
          <h3 className="mb-3 font-semibold text-white">Vacancy rate by trust (top 12)</h3>
          {wf.isLoading ? (
            <Skeleton className="h-96" />
          ) : (
            <ResponsiveContainer width="100%" height={420}>
              <BarChart data={data} layout="vertical" margin={{ left: 40, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} unit="%" />
                <YAxis type="category" dataKey="short" tick={{ fill: "#cbd5e1", fontSize: 10 }} width={150} />
                <Tooltip content={chartTooltip} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                <Bar dataKey="vacancy_rate" name="Vacancy %" radius={[0, 6, 6, 0]}>
                  {data.map((d, i) => (
                    <Cell key={i} fill={barColor(d.vacancy_rate)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </GlassCard>

        <GlassCard className="xl:col-span-2">
          <h3 className="mb-3 font-semibold text-white">Recommended actions</h3>
          <div className="flex max-h-[420px] flex-col gap-3 overflow-y-auto pr-1">
            {recs.isLoading
              ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20" />)
              : (recs.data ?? []).map((r) => (
                  <div key={r.recommendation_id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                    <div className="mb-1 flex items-center gap-2">
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        style={{ background: `${sevColor[r.severity] ?? "#64748b"}22`, color: sevColor[r.severity] ?? "#94a3b8" }}
                      >
                        {r.severity} · {r.category}
                      </span>
                      <span className="truncate text-xs text-slate-400">{r.hospital_name}</span>
                    </div>
                    <p className="text-sm text-slate-200">{r.action}</p>
                    {r.expected_impact && <p className="mt-1 text-xs text-nhs-cyan">→ {r.expected_impact}</p>}
                  </div>
                ))}
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
