import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "#090d16", // Deep enterprise charcoal navy
        surface: "#0f172a",    // Slate 900
        surfaceLight: "#1e293b", // Slate 800
        border: "#334155",      // Slate 700
        primary: {
          DEFAULT: "#0284c7",   // Sky 600
          foreground: "#ffffff",
          dark: "#0369a1",
        },
        accent: {
          emerald: "#10b981",  // Emerald 500
          cyan: "#06b6d4",     // Cyan 500
          amber: "#f59e0b",    // Amber 500
          rose: "#f43f5e",     // Rose 500
        },
      },
    },
  },
  plugins: [],
};
export default config;
