import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        enamel: "#E9EDE8", // app background
        surface: "#F8F9F6",
        white: "#FFFFFF",
        ink: "#1C2626", // main text
        "ink-muted": "#5B6863",
        "ink-faint": "#8A958F",
        line: "#D3D9D3", // borders, dividers
        green: "#2E5B4E", // primary buttons, brand
        "green-deep": "#1F4239", // brand panel, headings accent
        "green-tint": "#D6E3DC",
        manual: "#3B5675",
        "manual-tint": "#DCE4EE",
        history: "#9A6F22",
        "history-tint": "#F1E6CF",
        safety: "#F3C53A",
        "safety-tint": "#FBF0C8",
        alert: "#B0412C",
        "alert-tint": "#F5DCD5",
      },
      fontFamily: {
        head: "var(--font-heading)",
        body: "var(--font-body)",
      },
      borderRadius: {
        card: "22px",
        btn: "18px",
        input: "16px",
      },
    },
  },
  plugins: [tailwindcssAnimate],
} satisfies Config;
