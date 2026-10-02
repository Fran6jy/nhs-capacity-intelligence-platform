import { useId, useState } from "react";
import type { TooltipProps } from "recharts";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Table2, LineChart as LineIcon } from "lucide-react";
import clsx from "clsx";

/**
 * Chart kit — the few fixed decisions every chart shares.
 *
 * Series colours are a validated categorical set in fixed order (never
 * cycled, never reassigned when a series is filtered out). Observed /
 * published values are neutral ink, so a forecast or model always reads as
 * the coloured thing on top of the grey truth. Status colours (risk
 * red/amber/green) are not series colours and never appear here.
 */
export const SERIES = ["#12a5b3", "#d95926", "#9085e9", "#d55181"] as const;
export const ACTUAL = "#94a3b8";
export const GRID = "rgba(255,255,255,0.07)";
export const AXIS = "rgba(255,255,255,0.16)";
export const TICK = { fill: "#94a3b8", fontSize: 11 } as const;

/** Recharts cursor for line/area charts: a hairline crosshair, not a block. */
export const CROSSHAIR = { stroke: "rgba(255,255,255,0.25)", strokeWidth: 1 } as const;
/** Recharts cursor for bars: a faint wash on the hovered band. */
export const BAR_CURSOR = { fill: "rgba(255,255,255,0.04)" } as const;

export const fmtNumber = (v: number, digits = 1) =>
  Math.abs(v) >= 1_000_000
    ? `${(v / 1_000_000).toFixed(2)}M`
    : Math.abs(v) >= 10_000
      ? `${(v / 1_000).toFixed(0)}K`
      : v.toLocaleString("en-GB", { maximumFractionDigits: digits });

export type LegendItem = { name: string; color: string; kind?: "line" | "area" | "bar" | "band" | "dashed" };

/** Legend: always present for two or more series. Mirrors the mark it keys. */
export function ChartLegend({ items, className }: { items: LegendItem[]; className?: string }) {
  if (items.length < 2) return null;
  return (
    <ul className={clsx("flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-slate-300", className)} aria-label="Legend">
      {items.map((it) => (
        <li key={it.name} className="flex items-center gap-1.5">
          <Swatch color={it.color} kind={it.kind ?? "line"} />
          <span>{it.name}</span>
        </li>
      ))}
    </ul>
  );
}

function Swatch({ color, kind }: { color: string; kind: NonNullable<LegendItem["kind"]> }) {
  if (kind === "bar") return <span className="h-3 w-3 rounded-[3px]" style={{ background: color }} />;
  if (kind === "area" || kind === "band")
    return <span className="h-3 w-3.5 rounded-[3px]" style={{ background: color, opacity: kind === "band" ? 0.35 : 0.55 }} />;
  if (kind === "dashed")
    return <span className="h-0 w-4 border-t-2 border-dashed" style={{ borderColor: color }} />;
  return <span className="h-0.5 w-4 rounded-full" style={{ background: color }} />;
}

/** Glassy tooltip. Values lead; series are keyed with a short line, not a box. */
export function chartTooltip(props: TooltipProps<number, string>) {
  const { active, payload, label } = props;
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p) => p.value != null && !Array.isArray(p.value));
  return (
    <div className="rounded-xl border border-white/10 bg-ink-700 px-3 py-2 text-xs shadow-card">
      {label != null && <div className="mb-1.5 font-medium text-slate-400">{String(label)}</div>}
      {rows.map((p, i) => (
        <div key={i} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-2 text-slate-400">
            <span className="h-0.5 w-3.5 rounded-full" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-semibold tabular-nums text-white">
            {typeof p.value === "number" ? p.value.toLocaleString("en-GB", { maximumFractionDigits: 1 }) : String(p.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

export type Column<T> = { key: keyof T & string; label: string; format?: (v: unknown) => string; align?: "left" | "right" };

/**
 * Chart frame with a table-view twin.
 *
 * Every chart has an equivalent that needs no hover and no colour vision:
 * the same rows, as a table. The toggle sits in the frame's own header so
 * it is never confused with a page-level filter.
 */
export function ChartFrame<T extends object>({
  title, subtitle, legend, rows, columns, children, right, ariaLabel,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  legend?: LegendItem[];
  rows: T[];
  columns: Column<T>[];
  children: React.ReactNode;
  right?: React.ReactNode;
  ariaLabel?: string;
}) {
  const [table, setTable] = useState(false);
  const id = useId();
  return (
    <section aria-label={ariaLabel}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold text-white">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {right}
          {rows.length > 0 && (
            <button
              type="button"
              onClick={() => setTable((t) => !t)}
              aria-pressed={table}
              aria-controls={id}
              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 ring-1 ring-white/10 transition hover:bg-white/[0.05] hover:text-white"
            >
              {table ? <LineIcon className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
              {table ? "Chart" : "Table"}
            </button>
          )}
        </div>
      </div>
      {legend && <ChartLegend items={legend} className="mb-2" />}
      <div id={id}>
        {table ? (
          <div className="max-h-[360px] overflow-auto rounded-xl border border-white/10">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-ink-700 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  {columns.map((c) => (
                    <th key={c.key} className={clsx("px-3 py-2 font-medium", c.align === "right" ? "text-right" : "text-left")}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {rows.map((r, i) => (
                  <tr key={i} className="text-slate-300">
                    {columns.map((c) => {
                      const v = (r as Record<string, unknown>)[c.key];
                      const text = c.format ? c.format(v) : v == null ? "—" : typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : String(v);
                      return <td key={c.key} className={clsx("px-3 py-1.5 tabular-nums", c.align === "right" ? "text-right" : "text-left")}>{text}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}


/** One series, one axis. Two of these side by side replace a dual-axis chart. */
export function SmallMultiple({
  title, data, dataKey, xKey, color, unit, id, tickFmt, height = 200,
}: {
  title: string; data: object[]; dataKey: string; xKey: string; color: string; unit: string; id: string;
  tickFmt?: (v: unknown) => string; height?: number;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-300">{title}</p>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.12} />
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
