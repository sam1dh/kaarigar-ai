import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import resourcesToBackend from "i18next-resources-to-backend";
import {
  DEFAULT_LANG,
  browserToEnabledCode,
  isLanguageEnabled,
  scriptFor,
} from "./languages";
import { loadScriptFonts } from "./fonts";

const LANG_STORAGE_KEY = "kaarigar.lang";
const TEXT_SIZE_STORAGE_KEY = "kaarigar.textSize";

export type TextSizeValue = "normal" | "large" | "xlarge";

/** Which language: after login → profile; before login → localStorage, else an enabled browser language, else en-IN. */
export function initialLanguage(profileLanguage?: string): string {
  if (profileLanguage && isLanguageEnabled(profileLanguage)) return profileLanguage;
  const stored = localStorage.getItem(LANG_STORAGE_KEY);
  if (stored && isLanguageEnabled(stored)) return stored;
  for (const tag of navigator.languages ?? []) {
    const code = browserToEnabledCode(tag);
    if (code) return code;
  }
  return DEFAULT_LANG;
}

export function storedTextSize(): "normal" | "large" | "xlarge" {
  const v = localStorage.getItem(TEXT_SIZE_STORAGE_KEY);
  return v === "large" || v === "xlarge" ? v : "normal";
}

export function applyTextSize(size: "normal" | "large" | "xlarge"): void {
  document.documentElement.dataset.textSize = size;
  localStorage.setItem(TEXT_SIZE_STORAGE_KEY, size);
}

/** Load fonts → set <html lang data-script> → switch i18n. */
export async function applyLanguage(code: string): Promise<void> {
  await loadScriptFonts(scriptFor(code));
  const lang = languageShortCode(code);
  document.documentElement.lang = lang;
  document.documentElement.dataset.script = scriptFor(code);
  await i18n.changeLanguage(code);
}

function languageShortCode(code: string): string {
  // "ta-IN" → "ta" for <html lang>
  return code.split("-")[0] ?? code;
}

/** User picked a language on the login screen (or in a menu while logged out). */
export async function chooseLanguage(code: string): Promise<void> {
  localStorage.setItem(LANG_STORAGE_KEY, code);
  await applyLanguage(code);
}

void i18n
  .use(initReactI18next)
  .use(
    resourcesToBackend((language: string) => import(`./locales/${language}.json`))
  )
  .init({
    lng: initialLanguage(),
    fallbackLng: "en-IN",
    interpolation: { escapeValue: false },
  });

// Apply the stored text size before first paint of screens that read it.
document.documentElement.dataset.textSize = storedTextSize();

// On boot: load the initial language's fonts and set <html lang data-script>
// (the login screen has no session, so loadProfile won't do it).
void applyLanguage(initialLanguage());

export default i18n;
