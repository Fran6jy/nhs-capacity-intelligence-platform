import { Suspense, lazy } from "react";
import { Routes, Route } from "react-router-dom";
import Background from "./components/Background";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";

// Route-based code splitting: each page (and its charts) loads on demand.
const Overview = lazy(() => import("./pages/Overview"));
const Forecasting = lazy(() => import("./pages/Forecasting"));
const Workforce = lazy(() => import("./pages/Workforce"));
const RiskMap = lazy(() => import("./pages/RiskMap"));
const AiInsights = lazy(() => import("./pages/AiInsights"));

export default function App() {
  return (
    <>
      <Background />
      <Layout>
        <Suspense fallback={<div className="grid place-items-center p-16"><Spinner label="Loading…" /></div>}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/forecasting" element={<Forecasting />} />
            <Route path="/workforce" element={<Workforce />} />
            <Route path="/risk" element={<RiskMap />} />
            <Route path="/ai" element={<AiInsights />} />
          </Routes>
        </Suspense>
      </Layout>
    </>
  );
}
