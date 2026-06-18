import { useQuery, useMutation } from "@tanstack/react-query";

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ---- types (mirror src/api/schemas.py) ----
export interface KPIs {
  latest_date: string | null;
  ae_attendances: number;
  avg_bed_occupancy_pct: number;
  total_waiting_list: number;
  avg_vacancy_rate: number;
  trusts_red: number;
}
export interface PressurePoint {
  date_key: string;
  ae_attendances: number;
  admissions: number;
  discharges: number;
  avg_bed_occupancy_pct: number;
  total_waiting_list: number;
  avg_vacancy_rate: number;
}
export interface RiskRow {
  hospital_name: string;
  region_name: string;
  classification: "Green" | "Amber" | "Red";
  score: number;
  date_key: string;
}
export interface RegionalRisk {
  region_id: string;
  region_name: string;
  red_count: number;
  amber_count: number;
  green_count: number;
  avg_score: number;
}
export interface ForecastRow {
  date_key: string;
  hospital_name: string | null;
  specialty_name: string | null;
  target: string;
  horizon_days: number;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
  model: string;
}
export interface WorkforceRow {
  hospital_name: string;
  region_id: string;
  staff_count: number;
  vacancies: number;
  vacancy_rate: number;
}
export interface Recommendation {
  recommendation_id: number;
  hospital_name: string | null;
  severity: string;
  category: string;
  action: string;
  expected_impact: string | null;
}
export interface StreamMinute {
  minute_ts: string;
  attendances: number;
  ambulance: number;
  breach_risk: number;
}
export interface StreamAe {
  available: boolean;
  minutes: StreamMinute[];
  totals: { attendances: number; ambulance: number; breach_risk: number };
}
export interface AskResponse {
  question: string;
  answer: string;
  sql: string;
  rows: Record<string, unknown>[];
  provider: string;
}

// ---- hooks ----
export const useKpis = () => useQuery({ queryKey: ["kpis"], queryFn: () => get<KPIs>("/api/overview/kpis") });
export const usePressure = (days = 90) =>
  useQuery({ queryKey: ["pressure", days], queryFn: () => get<PressurePoint[]>(`/api/overview/national-pressure?days=${days}`) });
export const useRiskTop = () => useQuery({ queryKey: ["risk-top"], queryFn: () => get<RiskRow[]>("/api/risk/top") });
export const useRiskRegional = () => useQuery({ queryKey: ["risk-regional"], queryFn: () => get<RegionalRisk[]>("/api/risk/regional") });
export const useRiskDistribution = () =>
  useQuery({ queryKey: ["risk-dist"], queryFn: () => get<{ classification: string; n: number }[]>("/api/risk/distribution") });
export const useForecasts = (target: string, horizon: number) =>
  useQuery({ queryKey: ["forecasts", target, horizon], queryFn: () => get<ForecastRow[]>(`/api/forecasts?target=${target}&horizon=${horizon}`) });
export const useWorkforce = () => useQuery({ queryKey: ["workforce"], queryFn: () => get<WorkforceRow[]>("/api/workforce") });
export const useRecommendations = () => useQuery({ queryKey: ["recs"], queryFn: () => get<Recommendation[]>("/api/recommendations") });
export const useStreamAe = () =>
  useQuery({ queryKey: ["stream-ae"], queryFn: () => get<StreamAe>("/api/stream/ae"), refetchInterval: 15_000 });

export const useAsk = () =>
  useMutation({
    mutationFn: async (question: string): Promise<AskResponse> => {
      const res = await fetch(`${BASE}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.json();
    },
  });
