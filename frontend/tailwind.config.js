/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // The one accent. Used on the active thing and nowhere else.
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
        // dark chart surface (#0f1527) with the dataviz palette checks.
        // Slot 1 is the brand cyan stepped down — #00C2D1 itself is too light
        // for a 2px line on this surface.
        series: {
          1: "#12a5b3",
          2: "#d95926",
          3: "#9085e9",
          4: "#d55181",
        },
        // Surfaces: a flat, deep page and one panel tone. Depth comes from
        // hairlines and whitespace, not blur or glow.
        ink: {
          950: "#070b17",
          900: "#0a0f1e",
          800: "#0f1527",
          700: "#161e33",
          600: "#1f2941",
        },
      },
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        // Kept for a single use: lifting a floating element (tooltip) off the page.
        card: "0 12px 40px -16px rgba(0,0,0,0.7)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};
