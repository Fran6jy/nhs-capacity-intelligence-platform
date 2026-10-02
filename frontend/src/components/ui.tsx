import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useEffect } from "react";
import type { LucideIcon } from "lucide-react";
import clsx from "clsx";

/**
 * Panel. No entrance animation: a card fading in signals nothing, and on a
 * throttled tab it left content invisible. The one motion kept is the
 * number count-up, which means "this just loaded".
 */
export function GlassCard({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
  /** Kept for call-site compatibility; no longer used. */
  delay?: number;
}) {
  return <div className={clsx("glass glass-hover p-5 sm:p-6", className)}>{children}</div>;
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

/** Status: a square swatch and the word. Colour never carries it alone. */
export function RiskPill({ level }: { level: string }) {
  const swatch: Record<string, string> = { Red: "bg-risk-red", Amber: "bg-risk-amber", Green: "bg-risk-green" };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-200">
      <span className={clsx("h-2 w-2 rounded-[2px]", swatch[level] ?? "bg-slate-500")} aria-hidden />
      {level}
    </span>
  );
}

/**
 * Provenance mark — the product's signature detail.
 *
 * A short vertical rule in the provenance colour, then the word in small
 * caps. Quiet enough to sit on every section; distinctive enough to be
 * recognised at a glance. It is the one place colour carries the meaning
 * "whose number is this", and the word is always beside it.
 */
export type Provenance = "real" | "modelled" | "live";
const PROVENANCE: Record<Provenance, { label: string; rule: string; title: string }> = {
  real: { label: "Real", rule: "bg-risk-green", title: "Published by NHS England. Not modelled, not simulated." },
  modelled: { label: "Modelled", rule: "bg-slate-500", title: "Synthetic or model-derived. NHS England publishes monthly; anything finer is inferred." },
  live: { label: "Simulated live", rule: "bg-nhs-cyan", title: "A behavioural digital twin of a department feed, refreshing every 15 seconds." },
};

export function ProvenanceTag({ kind, className }: { kind: Provenance; className?: string }) {
  const p = PROVENANCE[kind];
  return (
    <span
      title={p.title}
      className={clsx("inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300", className)}
    >
      <span className={clsx("h-3 w-[2px] rounded-full", p.rule)} aria-hidden />
      {p.label}
    </span>
  );
}

/** Section heading with an optional provenance mark and right-hand slot. */
export function SectionHeading({
  title, kind, children, right,
}: { title: React.ReactNode; kind?: Provenance; children?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-base font-semibold text-white">{title}</h3>
          {kind && <ProvenanceTag kind={kind} />}
        </div>
        {children && <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-400">{children}</p>}
      </div>
      {right}
    </div>
  );
}

export function SectionTitle({ title, subtitle, eyebrow }: { title: string; subtitle?: string; eyebrow?: string }) {
  return (
    <div className="mb-8">
      {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
      <h1 className="text-3xl font-semibold tracking-[-0.02em] text-white sm:text-4xl">{title}</h1>
      {subtitle && <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-slate-400">{subtitle}</p>}
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
        <div className="mx-auto mb-3 grid h-10 w-10 place-items-center rounded-lg border border-white/10 text-slate-400">
          <Icon className="h-5 w-5" />
        </div>
        <p className="text-sm font-medium text-slate-200">{title}</p>
        {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}
