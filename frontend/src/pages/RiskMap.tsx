import { useState } from "react";
import { motion } from "framer-motion";
import { ShieldCheck } from "lucide-react";
import { useProviderRisk, useRiskRegional, type ProviderRisk } from "../lib/api";
import { GlassCard, SectionTitle, Skeleton } from "../components/ui";
import clsx from "clsx";

function scoreColor(s: number) {
  if (s >= 1) return { ring: "ring-risk-red/50", glow: "rgba(239,68,68,0.5)", label: "Red", text: "text-risk-red" };
  if (s >= 0) return { ring: "ring-risk-amber/50", glow: "rgba(245,158,11,0.45)", label: "Amber", text: "text-risk-amber" };
  return { ring: "ring-risk-green/50", glow: "rgba(34,197,94,0.4)", label: "Green", text: "text-risk-green" };
}

const CLASS_TONE: Record<ProviderRisk["classification"], string> = {
  Red: "bg-risk-red/15 text-risk-red ring-risk-red/40",
  Amber: "bg-risk-amber/15 text-risk-amber ring-risk-amber/40",
  Green: "bg-risk-green/15 text-risk-green ring-risk-green/40",
};

const COVERAGE_LABEL: Record<ProviderRisk["coverage"], string> = {
  "rtt+ae": "RTT + A&E",
  rtt: "RTT only",
  ae: "A&E only",
};

const pct = (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}%`);
const num = (v: number | null) => (v == null ? "—" : v.toLocaleString("en-GB"));

/** Peer-relative risk across the real NHS providers, worst first. */
function ProviderRiskPanel() {
  const [region, setRegion] = useState<string | undefined>(undefined);
  const q = useProviderRisk(25, region);
  const all = useProviderRisk(600);
  const regions = Array.from(
    new Set((all.data?.providers ?? []).map((p) => p.region_name).filter(Boolean) as string[]),
  ).sort();

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (!q.data?.available || q.data.providers.length === 0) {
    return <p className="text-sm text-slate-400">Provider risk not loaded yet — run <code className="text-nhs-cyan">scripts/ingest_nhs_real.py</code>.</p>;
  }

  const s = q.data.summary;
  const total = (s.Red ?? 0) + (s.Amber ?? 0) + (s.Green ?? 0) || 1;
  const worst = q.data.providers;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-3">
          {(["Red", "Amber", "Green"] as const).map((c) => (
            <span key={c} className={clsx("rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1", CLASS_TONE[c])}>
              {s[c] ?? 0} {c}
            </span>
          ))}
          <span className="text-xs text-slate-400">of {q.data.peer_count} providers</span>
        </div>
        <div className="ml-auto flex h-2 w-48 overflow-hidden rounded-full bg-white/5">
          <div className="bg-risk-red" style={{ width: `${((s.Red ?? 0) / total) * 100}%` }} />
          <div className="bg-risk-amber" style={{ width: `${((s.Amber ?? 0) / total) * 100}%` }} />
          <div className="bg-risk-green" style={{ width: `${((s.Green ?? 0) / total) * 100}%` }} />
        </div>
        <select
          value={region ?? ""}
          onChange={(e) => setRegion(e.target.value || undefined)}
          className="rounded-xl bg-white/[0.04] px-3 py-1.5 text-sm text-slate-200 ring-1 ring-white/10 focus:outline-none focus:ring-nhs-cyan/50"
          aria-label="Filter by NHS region"
        >
          <option value="">All regions</option>
          {regions.map((r) => (
            <option key={r} value={r}>{r.replace("NHS ENGLAND ", "")}</option>
          ))}
        </select>
      </div>

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-white/[0.04] text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Provider</th>
              <th className="px-3 py-2 text-left font-medium">Region</th>
              <th className="px-3 py-2 text-left font-medium">Inputs</th>
              <th className="px-3 py-2 text-right font-medium">Within 18w</th>
              <th className="px-3 py-2 text-right font-medium">4-hour</th>
              <th className="px-3 py-2 text-right font-medium">Waiting</th>
              <th className="px-3 py-2 text-right font-medium">Score</th>
              <th className="px-3 py-2 text-left font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {worst.map((p) => (
              <tr key={p.org_code} className="text-slate-300 transition hover:bg-white/[0.03]">
                <td className="px-3 py-2">
                  <div className="font-medium text-white">{p.org_name ?? p.org_code}</div>
                  <div className="text-[11px] text-slate-500">{p.org_code}</div>
                </td>
                <td className="px-3 py-2 text-slate-400">{(p.region_name ?? "—").replace("NHS ENGLAND ", "")}</td>
                <td className="px-3 py-2 text-slate-400">{COVERAGE_LABEL[p.coverage]}</td>
                <td className="px-3 py-2 text-right tabular-nums">{pct(p.within_18_weeks_pct)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{pct(p.four_hour_performance_pct)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-400">{num(p.total_waiting)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{p.score.toFixed(2)}</td>
                <td className="px-3 py-2">
                  <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1", CLASS_TONE[p.classification])}>
                    {p.classification}
                  </span>
                  {p.trigger === "absolute" && (
                    <span className="ml-1.5 text-[10px] uppercase tracking-wide text-slate-500" title="Escalated by an absolute threshold, not by peer ranking">abs</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Scored on NHS England's latest published month: share of the waiting list beyond 18 and 52
        weeks, share of A&E attendances beyond four hours, and twelve-hour waits per thousand
        attendances, each z-scored against the full peer set. "abs" marks a provider escalated by an
        absolute threshold (within-18-weeks below 50%, four-hour below 60%) regardless of how it
        ranks against peers.
      </p>
    </>
  );
}

export default function RiskMap() {
  const q = useRiskRegional();
  const regions = (q.data ?? []).slice().sort((a, b) => b.avg_score - a.avg_score);

  return (
    <div>
      <SectionTitle title="Risk Map" subtitle="Peer-relative operational pressure — real providers, and the modelled regional composite" />

      <GlassCard>
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-risk-green" />
          <h3 className="font-semibold text-white">Highest-risk NHS providers</h3>
          <span className="rounded-full bg-risk-green/15 px-2 py-0.5 text-[11px] font-semibold text-risk-green ring-1 ring-risk-green/40">Real</span>
        </div>
        <p className="mb-4 text-xs text-slate-400">
          Every provider NHS England publishes an RTT waiting list or A&E activity for, ranked worst first.
        </p>
        <ProviderRiskPanel />
      </GlassCard>

      <div className="mb-3 mt-8 flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-white">Regional composite — modelled daily series</h3>
        <span className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] font-semibold text-slate-300 ring-1 ring-white/15">Modelled</span>
      </div>

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
