/** @type {import('tailwindcss').Config} */
module.exports = {
  prefix: "tw-",
  corePlugins: {
    preflight: false,
  },
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./lib/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        neyra: {
          bg: "#090b10",
          panel: "#10131c",
          violet: "#7c5cff",
          cyan: "#22f3ff",
          rose: "#ff4fd8",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Inter",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        "paywall-glow": "0 20px 60px rgba(124, 92, 255, 0.25), 0 0 80px rgba(255, 79, 216, 0.12)",
        "paywall-plus": "0 24px 70px rgba(255, 79, 216, 0.35), 0 0 100px rgba(124, 92, 255, 0.2)",
      },
      scale: {
        102: "1.02",
        103: "1.03",
      },
    },
  },
  plugins: [],
};
