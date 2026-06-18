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
} from "lucide-react";
import clsx from "clsx";

const NAV = [
  { to: "/", label: "Executive Overview", icon: LayoutDashboard, end: true },
  { to: "/forecasting", label: "Forecasting", icon: LineChart },
  { to: "/workforce", label: "Workforce", icon: Users },
  { to: "/risk", label: "Risk Map", icon: Map },
  { to: "/ai", label: "AI Insights", icon: Sparkles },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-2 border-r border-white/10 bg-ink-800/60 p-5 backdrop-blur-xl lg:flex">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-nhs-blue to-nhs-cyan shadow-glow">
            <HeartPulse className="h-6 w-6 text-white" />
          </div>
          <div>
            <div className="text-sm font-bold leading-tight text-white">NHS Capacity</div>
            <div className="text-[11px] text-slate-400">Demand Intelligence</div>
          </div>
        </div>

        <nav className="flex flex-col gap-1">
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
                  <n.icon className="h-[18px] w-[18px]" />
                  {n.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto rounded-xl border border-white/10 bg-white/[0.03] p-3 text-[11px] text-slate-400">
          <div className="flex items-center gap-2 text-emerald-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            Live · PostgreSQL
          </div>
          <p className="mt-1 leading-relaxed">Predictive + prescriptive NHS operations.</p>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/10 bg-ink-900/60 px-6 py-4 backdrop-blur-xl">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Activity className="h-4 w-4 text-nhs-cyan" />
            <span className="text-gradient font-semibold">Capacity & Demand Intelligence Platform</span>
          </div>
          <div className="hidden items-center gap-2 text-xs text-slate-400 sm:flex">
            <span className="rounded-full bg-white/[0.05] px-3 py-1 ring-1 ring-white/10">v1.0 · React + FastAPI</span>
          </div>
        </header>

        <main className="flex-1 px-5 py-6 sm:px-8">
          <AnimatePresence mode="wait">
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
      </div>
    </div>
  );
}
