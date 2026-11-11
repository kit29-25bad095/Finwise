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
        canvas: "#F9FAFB",
        surface: "#FFFFFF",
        ink: {
          primary: "#09090B",
          secondary: "#71717A",
          muted: "#A1A1AA",
        },
        border: {
          DEFAULT: "#E4E4E7",
          subtle: "#E4E4E7",
          dark: "#D4D4D8",
        },
        hover: "#F4F4F5",
        brand: {
          black: "#18181B",
          dark: "#09090B",
        },
        semantic: {
          leakage: {
            text: "#DC2626",
            bg: "#FEF2F2",
            border: "#FECACA",
          },
          pending: {
            text: "#D97706",
            bg: "#FFFBEB",
            border: "#FDE68A",
          },
          matched: {
            text: "#52525B",
            bg: "#F4F4F5",
            border: "#E4E4E7",
          },
        },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "Consolas", "Liberation Mono", "Menlo", "monospace"],
      },
      width: {
        sidebar: "220px",
        drawer: "480px",
      },
      height: {
        topbar: "56px",
        tableRow: "44px",
      },
    },
  },
  plugins: [],
};
export default config;
