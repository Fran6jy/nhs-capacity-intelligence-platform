import { motion } from "framer-motion";
import { useRiskRegional } from "../lib/api";
import { SectionTitle, Skeleton } from "../components/ui";

function scoreColor(s: number) {
  if (s >= 1) return { ring: "ring-risk-red/50", glow: "rgba(239,68,68,0.5)", label: "Red", text: "text-risk-red" };
  if (s >= 0) return { ring: "ring-risk-amber/50", glow: "rgba(245,158,11,0.45)", label: "Amber", text: "text-risk-amber" };
  return { ring: "ring-risk-green/50", glow: "rgba(34,197,94,0.4)", label: "Green", text: "text-risk-green" };
}

export default function RiskMap() {
  const q = useRiskRegional();
  const regions = (q.data ?? []).slice().sort((a, b) => b.avg_score - a.avg_score);

  return (
    <div>
      <SectionTitle title="Regional Risk Map" subtitle="Composite operational pressure by NHS region (latest)" />

      {q.isLoading ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-40" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {regions.map((r, i) => {
            const c = scoreColor(r.avg_score);
            const total = r.red_count + r.amber_count + r.green_count || 1;
            return (
              <motion.div
                key={r.region_id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.05 }}
                className={`glass glass-hover relative overflow-hidden p-5 ring-1 ${c.ring}`}
                style={{ boxShadow: `0 0 32px -14px ${c.glow}` }}
              >
                <div className="absolute right-3 top-3 h-2.5 w-2.5 animate-pulse rounded-full" style={{ background: c.glow }} />
                <p className="text-xs uppercase tracking-wide text-slate-400">{r.region_id}</p>
                <h3 className="text-lg font-semibold text-white">{r.region_name}</h3>
                <p className={`mt-2 text-3xl font-bold ${c.text}`}>{r.avg_score?.toFixed(2)}</p>
                <p className="text-[11px] text-slate-400">avg composite score</p>

                <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-white/5">
                  <div className="bg-risk-red" style={{ width: `${(r.red_count / total) * 100}%` }} />
                  <div className="bg-risk-amber" style={{ width: `${(r.amber_count / total) * 100}%` }} />
                  <div className="bg-risk-green" style={{ width: `${(r.green_count / total) * 100}%` }} />
                </div>
                <div className="mt-2 flex justify-between text-[11px] text-slate-400">
                  <span className="text-risk-red">{r.red_count} red</span>
                  <span className="text-risk-amber">{r.amber_count} amber</span>
                  <span className="text-risk-green">{r.green_count} green</span>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
