import { useState } from "react";
import { motion } from "framer-motion";
import { Database, Send, Sparkles } from "lucide-react";
import { useAsk, type AskResponse } from "../lib/api";
import { GlassCard, SectionTitle, Spinner } from "../components/ui";

const SUGGESTIONS = [
  "Why are cardiology waiting times increasing?",
  "Which hospitals are at risk of overload?",
  "Where will staffing shortages occur next?",
  "Why is A&E demand rising?",
];

type Msg = { role: "user" | "assistant"; text: string; meta?: AskResponse };

export default function AiInsights() {
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const ask = useAsk();

  const submit = (q: string) => {
    if (!q.trim() || ask.isPending) return;
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setInput("");
    ask.mutate(q, {
      onSuccess: (r) => setMsgs((m) => [...m, { role: "assistant", text: r.answer, meta: r }]),
      onError: (e) => setMsgs((m) => [...m, { role: "assistant", text: `Error: ${String(e)}` }]),
    });
  };

  return (
    <div>
      <SectionTitle title="AI Insights" subtitle="Ask in natural language — answered from PostgreSQL via retrieval-augmented generation" />

      <GlassCard className="flex h-[68vh] flex-col">
        {/* messages */}
        <div className="flex-1 space-y-4 overflow-y-auto pr-1">
          {msgs.length === 0 && (
            <div className="grid h-full place-items-center">
              <div className="text-center">
                <div className="mx-auto mb-4 grid h-14 w-14 animate-float place-items-center rounded-2xl bg-gradient-to-br from-nhs-blue to-nhs-cyan shadow-glow">
                  <Sparkles className="h-7 w-7 text-white" />
                </div>
                <p className="text-slate-300">Ask about demand, risk, forecasts or workforce.</p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => submit(s)}
                      className="rounded-full bg-white/[0.04] px-3.5 py-1.5 text-sm text-slate-300 ring-1 ring-white/10 transition hover:bg-nhs-cyan/10 hover:text-nhs-cyan hover:ring-nhs-cyan/30"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {msgs.map((m, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={m.role === "user" ? "max-w-[80%] rounded-2xl rounded-br-sm bg-nhs-blue/20 px-4 py-2.5 text-slate-100 ring-1 ring-nhs-blue/30" : "max-w-[85%] rounded-2xl rounded-bl-sm bg-white/[0.04] px-4 py-3 ring-1 ring-white/10"}>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.text}</p>
                {m.meta && (
                  <details className="mt-2 text-xs text-slate-400">
                    <summary className="flex cursor-pointer items-center gap-1.5 text-nhs-cyan/80">
                      <Database className="h-3.5 w-3.5" /> {m.meta.rows.length} rows · {m.meta.provider} · view SQL
                    </summary>
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-black/30 p-2 text-[11px] text-slate-300">{m.meta.sql.trim()}</pre>
                  </details>
                )}
              </div>
            </motion.div>
          ))}

          {ask.isPending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-white/[0.04] px-4 py-3 ring-1 ring-white/10">
                <Spinner label="Querying warehouse & reasoning…" />
              </div>
            </div>
          )}
        </div>

        {/* input */}
        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-white/10 bg-ink-800/60 p-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit(input)}
            placeholder="Ask the NHS intelligence assistant…"
            className="flex-1 bg-transparent px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
          />
          <button
            onClick={() => submit(input)}
            disabled={ask.isPending || !input.trim()}
            className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-nhs-blue to-nhs-cyan text-white shadow-glow transition disabled:opacity-40"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </GlassCard>
    </div>
  );
}
