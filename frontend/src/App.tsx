import { Routes, Route } from "react-router-dom";
import Background from "./components/Background";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import Forecasting from "./pages/Forecasting";
import Workforce from "./pages/Workforce";
import RiskMap from "./pages/RiskMap";
import AiInsights from "./pages/AiInsights";

export default function App() {
  return (
    <>
      <Background />
      <Layout>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/forecasting" element={<Forecasting />} />
          <Route path="/workforce" element={<Workforce />} />
          <Route path="/risk" element={<RiskMap />} />
          <Route path="/ai" element={<AiInsights />} />
        </Routes>
      </Layout>
    </>
  );
}
