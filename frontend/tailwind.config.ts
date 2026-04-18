import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0e1a",
        surface: "#111827",
        border: "#1f2937",
        accent: "#10b981",
        accentHover: "#059669",
        warn: "#f59e0b",
        danger: "#ef4444",
        muted: "#9ca3af",
      },
    },
  },
  plugins: [],
};

export default config;
