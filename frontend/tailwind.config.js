/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        nhs: {
          blue: "#0072CE",
          dark: "#003087",
          cyan: "#00C2D1",
        },
        // Status colours: reserved for meaning (good / warning / critical).
        // Never used as a series colour on a chart.
        risk: {
          green: "#22c55e",
          amber: "#f59e0b",
          red: "#ef4444",
        },
        // Categorical chart series, in fixed order. Validated on the app's
        // dark chart surface (#0f1527) with the dataviz palette checks:
        // lightness band, chroma floor, adjacent CVD ΔE ≥ 8, normal-vision
        // ΔE ≥ 15, contrast ≥ 3:1. Slot 1 is the brand cyan stepped down —
        // #00C2D1 itself is too light for a 2px line on this surface.
        series: {
          1: "#12a5b3",
          2: "#d95926",
          3: "#9085e9",
          4: "#d55181",
        },
        ink: {
          900: "#070b1a",
          800: "#0b1226",
          700: "#121b35",
          600: "#1b2647",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 40px -10px rgba(0,194,209,0.45)",
        card: "0 8px 40px -12px rgba(0,0,0,0.6)",
      },
      keyframes: {
        aurora: {
          "0%,100%": { transform: "translate(0,0) scale(1)", opacity: "0.55" },
          "50%": { transform: "translate(-6%,4%) scale(1.15)", opacity: "0.8" },
        },
        float: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        aurora: "aurora 18s ease-in-out infinite",
        "aurora-slow": "aurora 26s ease-in-out infinite",
        float: "float 6s ease-in-out infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};
