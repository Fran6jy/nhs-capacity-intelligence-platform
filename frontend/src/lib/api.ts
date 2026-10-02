import { useQuery, useMutation } from "@tanstack/react-query";

const BASE = import.meta.env.VITE_API_BASE ?? "";
const API_KEY = import.meta.env.VITE_API_KEY;

// Attach the API key header when configured (matches the API's API_KEY guard).
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return API_KEY ? { ...extra, "X-API-Key": API_KEY } : extra;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
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
// ---- real NHS England published statistics ----
export interface RttNational {
  period: string;
  total_waiting: number;
  over_18_weeks: number;
  over_52_weeks: number;
  within_18_weeks_pct: number;
}
export interface RttSpecialty {
  specialty_name: string;
  total_waiting: number;
  over_52_weeks: number;
  median_wait_weeks: number;
}
export interface NhsRtt {
  available: boolean;
  national?: RttNational[];
  by_specialty?: RttSpecialty[];
}

export interface AeNational {
  period: string;
  attendances: number;
  emergency_admissions: number;
  twelve_hour_waits: number;
  four_hour_performance_pct: number;
}
export interface AeRegion {
  region_name: string;
  attendances: number;
  four_hour_performance_pct: number;
}
export interface NhsAe {
  available: boolean;
  national?: AeNational[];
  by_region?: AeRegion[];
}

/** Which trust tier answered — see src/llm/nl2sql.py. */
export type AskSource = "curated" | "generated" | "unanswerable";

export interface AskResponse {
  question: string;
  answer: string;
  sql: string;
  rows: Record<string, unknown>[];
  provider: string;
  source: AskSource;
  intent: string | null;
  explanation: string;
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

export interface OpsMinute {
  minute_ts: string;
  arrivals: number;
  available_beds: number;
  queue_length: number;
  ambulances_waiting: number;
  occupancy_pct: number;
  breach_risk: number;
}
export interface OpsState {
  available: boolean;
  minutes: OpsMinute[];
  latest: {
    minute_ts?: string;
    arrivals: number;
    occupancy_pct: number;
    available_beds: number;
    queue_length: number;
    ambulances_waiting: number;
    breach_risk: number;
  };
}
export interface OpsExplain {
  metrics: {
    arrivals_vs_baseline_pct: number;
    occupancy_pct: number;
    available_beds_now: number;
    available_beds_change: number;
    queue_now: number;
    ambulances_waiting_now: number;
    ambulances_vs_baseline_pct: number;
  };
  narrative: string;
  provider: string;
}
export const useOpsState = () =>
  useQuery({ queryKey: ["ops-state"], queryFn: () => get<OpsState>("/api/ops/state"), refetchInterval: 15_000 });
export const useOpsExplain = () =>
  useMutation({ mutationFn: () => get<OpsExplain>("/api/ops/explain") });

export interface DataSource { name: string; category: string; kind: "real" | "modelled"; detail: string; }
/** One row per forecaster from the rolling-origin back-test (src/models/validation.py). */
export interface ModelMetric {
  target: string;
  model: string;
  folds: number;
  horizon_days: number;
  mae: number;
  mae_std: number | null;
  mape: number | null;
  mase: number | null;
  /** The trivial forecast the model is measured against. */
  baseline: "seasonal_naive" | "last_value" | "persistence";
  baseline_mae: number;
  /** Fraction of baseline error removed; <= 0 means no better than guessing. */
  skill: number;
  n_eval: number;
}
export interface ForecastActual { target: string; date: string; actual: number; predicted: number; baseline: number; }
export const useValidationSources = () =>
  useQuery({ queryKey: ["val-sources"], queryFn: () => get<DataSource[]>("/api/validation/sources") });
export const useValidationMetrics = () =>
  useQuery({ queryKey: ["val-metrics"], queryFn: () => get<{ available: boolean; metrics: ModelMetric[] }>("/api/validation/metrics") });
export const useForecastActual = () =>
  useQuery({ queryKey: ["val-fa"], queryFn: () => get<{ available: boolean; series: ForecastActual[] }>("/api/validation/forecast-actual") });
export const useNhsRtt = () =>
  useQuery({ queryKey: ["nhs-rtt"], queryFn: () => get<NhsRtt>("/api/nhs/rtt?limit=8") });
export const useNhsAe = () =>
  useQuery({ queryKey: ["nhs-ae"], queryFn: () => get<NhsAe>("/api/nhs/ae?limit=7") });

// ---- real-data modelling: national monthly forecasts + provider risk ----
export interface RttHistoryPoint {
  period: string;
  total_waiting: number;
  within_18_weeks_pct: number;
  over_18_weeks: number;
  over_52_weeks: number;
  median_wait_weeks: number;
}
export interface MonthlyForecastPoint {
  target: string;
  period: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
  model: string;
  unit: string;
}
/** Back-test of a monthly forecast against "same month last year". */
export interface MonthlyMetric {
  target: string;
  model: string;
  folds: number;
  horizon_months: number;
  unit: string;
  mae: number;
  mae_std: number | null;
  mape: number | null;
  mase: number | null;
  baseline: string;
  baseline_mae: number;
  skill: number;
  n_eval: number;
  /** How many candidate models competed on the same folds. */
  candidates_tried: number;
}
export interface ProviderRisk {
  org_code: string;
  org_name: string | null;
  region_name: string | null;
  coverage: "rtt+ae" | "rtt" | "ae";
  score: number;
  classification: "Green" | "Amber" | "Red";
  trigger: "absolute" | "peer-relative";
  within_18_weeks_pct: number | null;
  four_hour_performance_pct: number | null;
  total_waiting: number | null;
  attendances: number | null;
  rtt_period: string | null;
  ae_period: string | null;
  peer_count: number;
  components_json: string;
}
export interface ProviderRiskResponse {
  available: boolean;
  summary: Partial<Record<"Green" | "Amber" | "Red", number>>;
  peer_count: number;
  providers: ProviderRisk[];
}

export const useRttHistory = (months = 120) =>
  useQuery({
    queryKey: ["nhs-rtt-history", months],
    queryFn: () => get<{ available: boolean; series: RttHistoryPoint[] }>(`/api/nhs/rtt/history?months=${months}`),
  });
export const useNhsForecast = () =>
  useQuery({
    queryKey: ["nhs-forecast"],
    queryFn: () => get<{ available: boolean; targets: string[]; series: MonthlyForecastPoint[] }>("/api/nhs/forecast"),
  });
export const useNhsForecastMetrics = () =>
  useQuery({
    queryKey: ["nhs-forecast-metrics"],
    queryFn: () => get<{ available: boolean; metrics: MonthlyMetric[] }>("/api/nhs/forecast-metrics"),
  });
export const useProviderRisk = (limit = 25, region?: string) =>
  useQuery({
    queryKey: ["nhs-provider-risk", limit, region ?? ""],
    queryFn: () =>
      get<ProviderRiskResponse>(
        `/api/nhs/provider-risk?limit=${limit}${region ? `&region=${encodeURIComponent(region)}` : ""}`,
      ),
  });

export const useAsk = () =>
  useMutation({
    mutationFn: async (question: string): Promise<AskResponse> => {
      const res = await fetch(`${BASE}/api/ask`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ question }),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.json();
    },
  });
