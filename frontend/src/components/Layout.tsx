import { useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  LayoutDashboard,
  LineChart,
  Users,
  Map,
  Sparkles,
  HeartPulse,
  ShieldCheck,
} from "lucide-react";
import clsx from "clsx";
import { ProvenanceTag } from "./ui";

const NAV = [
  { to: "/", label: "Executive Overview", short: "Overview", icon: LayoutDashboard, end: true },
  { to: "/forecasting", label: "Forecasting", short: "Forecast", icon: LineChart },
  { to: "/workforce", label: "Workforce", short: "Workforce", icon: Users },
  { to: "/risk", label: "Risk Map", short: "Risk", icon: Map },
  { to: "/ai", label: "AI Insights", short: "AI", icon: Sparkles },
  { to: "/evidence", label: "Evidence & Validation", short: "Evidence", icon: ShieldCheck },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation();

  // The browser tab should say where you are, not just what the app is.
  useEffect(() => {
    const page = NAV.find((n) => (n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)));
    document.title = page ? `${page.label} · NHS Capacity Intelligence` : "NHS Capacity Intelligence";
  }, [loc.pathname]);

  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-nhs-cyan focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-ink-900"
      >
        Skip to content
      </a>

      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-2 border-r border-white/10 bg-ink-800/60 p-5 backdrop-blur-xl lg:flex" aria-label="Primary">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-nhs-blue to-nhs-cyan shadow-glow">
            <HeartPulse className="h-6 w-6 text-white" aria-hidden />
          </div>
          <div>
            <div className="text-sm font-bold leading-tight text-white">NHS Capacity</div>
            <div className="text-[11px] text-slate-400">Demand Intelligence</div>
          </div>
        </div>

        <nav className="flex flex-col gap-1" aria-label="Pages">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                clsx(
                  "group relative flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all",
                  isActive
                    ? "bg-white/[0.07] text-white shadow-glow"
                    : "text-slate-400 hover:bg-white/[0.04] hover:text-white"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="nav-active"
                      className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r bg-nhs-cyan"
                    />
                  )}
                  <n.icon className="h-[18px] w-[18px]" aria-hidden />
                  {n.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto rounded-xl border border-white/10 bg-white/[0.03] p-3 text-[11px] text-slate-400">
          <div className="flex items-center gap-2 text-emerald-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" aria-hidden />
            Live · PostgreSQL
          </div>
          <p className="mt-1 leading-relaxed">Published NHS England data, refreshed monthly; modelled layers refreshed twice daily.</p>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-white/10 bg-ink-900/60 px-4 py-3 backdrop-blur-xl sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center gap-2 text-sm text-slate-400">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-nhs-blue to-nhs-cyan lg:hidden">
              <HeartPulse className="h-4 w-4 text-white" aria-hidden />
            </div>
            <Activity className="hidden h-4 w-4 text-nhs-cyan lg:block" aria-hidden />
            <span className="text-gradient truncate font-semibold">Capacity & Demand Intelligence</span>
          </div>
          {/* The one thing every page needs the reader to know: which figures are whose. */}
          <div className="flex shrink-0 items-center gap-1.5" aria-label="How figures are labelled">
            <ProvenanceTag kind="real" />
            <ProvenanceTag kind="modelled" />
          </div>
        </header>

        <main id="main" className="flex-1 px-4 pb-24 pt-5 sm:px-8 sm:py-6 lg:pb-6" tabIndex={-1}>
          {/* initial={false}: the first route paints immediately rather than
              waiting on a JS-driven fade; only route-to-route changes animate. */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={loc.pathname}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28 }}
              className="mx-auto max-w-7xl"
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>

        {/* Bottom tab bar (mobile / tablet) — the sidebar does not exist below lg. */}
        <nav
          className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-6 border-t border-white/10 bg-ink-900/90 px-1 pb-[max(env(safe-area-inset-bottom),4px)] pt-1 backdrop-blur-xl lg:hidden"
          aria-label="Pages"
        >
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                clsx(
                  "flex flex-col items-center gap-0.5 rounded-lg px-1 py-1.5 text-[10px] font-medium transition",
                  isActive ? "text-nhs-cyan" : "text-slate-400 hover:text-white"
                )
              }
            >
              <n.icon className="h-5 w-5" aria-hidden />
              <span className="truncate">{n.short}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
