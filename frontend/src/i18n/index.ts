import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import hi from "./locales/hi.json";
import mr from "./locales/mr.json";

export const LANGS = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "mr", label: "मराठी" },
] as const;

export type LangCode = (typeof LANGS)[number]["code"];

const STORAGE_KEY = "kaarigar.lang";

/** Map a users.language value (e.g. "hi-IN", "mr-IN") to an i18n code. */
export function profileLangToCode(language: string | undefined): LangCode {
  if (!language) return "en";
  if (language.startsWith("hi")) return "hi";
  if (language.startsWith("mr")) return "mr";
  return "en";
}

/** Convert an i18n code back to a users.language-style tag. */
export function codeToProfileLang(code: LangCode): string {
  return code === "hi" ? "hi-IN" : code === "mr" ? "mr-IN" : "en-IN";
}

/** Before login: the pill choice, persisted in localStorage (default English). */
export function getStoredLang(): LangCode {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "hi" || stored === "mr" || stored === "en") return stored;
  return "en";
}

export function storeLang(code: LangCode): void {
  localStorage.setItem(STORAGE_KEY, code);
}

export function applyLanguage(code: LangCode): void {
  void i18n.changeLanguage(code);
  document.documentElement.lang = code;
  // Devanagari font stack when showing Hindi/Marathi.
  document.body.classList.toggle("font-deva", code !== "en");
}

/** After login: default language follows the profile. */
export function setAppLanguage(profileLanguage: string | undefined): void {
  applyLanguage(profileLangToCode(profileLanguage));
}

/** User picked a language pill on the login screen. */
export function chooseLanguage(code: LangCode): void {
  storeLang(code);
  applyLanguage(code);
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    hi: { translation: hi },
    mr: { translation: mr },
  },
  lng: getStoredLang(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});
applyLanguage(getStoredLang());

export default i18n;
