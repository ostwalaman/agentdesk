import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#071426",
          900: "#0b1f3a",
          800: "#102a4c",
          700: "#173b68"
        },
        electric: {
          500: "#1f8cff",
          400: "#49a6ff",
          300: "#81c4ff"
        }
      },
      boxShadow: {
        soft: "0 18px 45px rgba(7, 20, 38, 0.16)"
      }
    }
  },
  plugins: [typography]
};
