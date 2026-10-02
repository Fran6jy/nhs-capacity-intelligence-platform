import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useEffect } from "react";
import { FlaskConical, Radio, ShieldCheck, type LucideIcon } from "lucide-react";
import clsx from "clsx";

export function GlassCard({
  className,
  children,
  delay = 0,
}: {
  className?: string;
  children: React.ReactNode;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
      className={clsx("glass glass-hover p-5 sm:p-6", className)}
    >
      {children}
    </motion.div>
  );
}

/** Spring-animated number counter. Proportional figures: this is a hero value. */
export function AnimatedNumber({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { stiffness: 90, damping: 20 });
  const text = useTransform(spring, (v) =>
    v.toLocaleString("en-GB", { maximumFractionDigits: decimals, minimumFractionDigits: decimals })
  );
  useEffect(() => {
    mv.set(value);
  }, [value, mv]);
  return <motion.span>{text}</motion.span>;
}

export function RiskPill({ level }: { level: string }) {
  const map: Record<string, string> = {
    Red: "bg-risk-red/15 text-risk-red ring-risk-red/40",
    Amber: "bg-risk-amber/15 text-risk-amber ring-risk-amber/40",
    Green: "bg-risk-green/15 text-risk-green ring-risk-green/40",
  };
  return (
    <span className={clsx("rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1", map[level] ?? map.Green)}>
      {level}
    </span>
  );
}

/**
 * Says where a figure comes from. Used on every section so a reader never has
 * to guess whether they are looking at NHS England's number or ours.
 */
export type Provenance = "real" | "modelled" | "live";
const PROVENANCE: Record<Provenance, { label: string; cls: string; icon: LucideIcon; title: string }> = {
  real: {
    label: "Real", icon: ShieldCheck,
    cls: "bg-risk-green/15 text-risk-green ring-risk-green/40",
    title: "Published by NHS England. Not modelled, not simulated.",
  },
  modelled: {
    label: "Modelled", icon: FlaskConical,
    cls: "bg-white/[0.06] text-slate-300 ring-white/15",
    title: "Synthetic or model-derived. NHS England publishes monthly; anything finer is inferred.",
  },
  live: {
    label: "Simulated live", icon: Radio,
    cls: "bg-nhs-cyan/10 text-nhs-cyan ring-nhs-cyan/30",
    title: "A behavioural digital twin of a department feed, refreshing every 15 seconds.",
  },
};

export function ProvenanceTag({ kind, className }: { kind: Provenance; className?: string }) {
  const p = PROVENANCE[kind];
  const Icon = p.icon;
  return (
    <span
      title={p.title}
      className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1", p.cls, className)}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {p.label}
    </span>
  );
}

/** Section heading with an optional provenance tag and right-hand slot. */
export function SectionHeading({
  title, kind, children, right,
}: { title: React.ReactNode; kind?: Provenance; children?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold text-white">{title}</h3>
          {kind && <ProvenanceTag kind={kind} />}
        </div>
        {children && <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400">{children}</p>}
      </div>
      {right}
    </div>
  );
}

export function SectionTitle({ title, subtitle, eyebrow }: { title: string; subtitle?: string; eyebrow?: string }) {
  return (
    <div className="mb-6">
      {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
      <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">{title}</h1>
      {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-400">{subtitle}</p>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-slate-400" role="status">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-nhs-cyan" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={clsx("relative overflow-hidden rounded-xl bg-white/[0.04]", className)} aria-hidden>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/10 to-transparent" />
    </div>
  );
}

/** A deliberate empty state: what is missing, and the one action that fixes it. */
export function EmptyState({
  icon: Icon, title, hint, action,
}: { icon: LucideIcon; title: string; hint?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="grid min-h-[200px] place-items-center rounded-xl border border-dashed border-white/10 p-6 text-center">
      <div>
        <div className="mx-auto mb-3 grid h-10 w-10 place-items-center rounded-xl bg-white/[0.05] text-slate-400 ring-1 ring-white/10">
          <Icon className="h-5 w-5" />
        </div>
        <p className="text-sm font-medium text-slate-200">{title}</p>
        {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}
