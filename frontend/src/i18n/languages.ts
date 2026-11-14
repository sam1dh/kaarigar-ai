/**
 * Typed view of shared/languages.json — the single source of truth
 * shared with the backend (app/core/languages.py). Adding a language later
 * means editing that JSON + adding one locale file. No code changes.
 */
import raw from "../../../shared/languages.json";

export interface LanguageDef {
  code: string; // e.g. "ta-IN"
  name: string; // English name, e.g. "Tamil"
  native: string; // e.g. "தமிழ்"
  region: "all" | "north" | "west" | "east" | "south";
  script:
    | "latn"
    | "deva"
    | "guru"
    | "gujr"
    | "beng"
    | "orya"
    | "taml"
    | "telu"
    | "knda"
    | "mlym"
    | "arab"
    | "olck";
  enabled: boolean;
  stt: boolean;
  tts: boolean;
}

export interface LanguageFile {
  default: string;
  languages: LanguageDef[];
}

export const LANGUAGES: LanguageDef[] = (raw as LanguageFile).languages;
export const DEFAULT_LANG = (raw as LanguageFile).default;

/** Languages shown in the app in Phase 0 (Sarvam STT + TTS both available). */
export const ENABLED_LANGUAGES: LanguageDef[] = LANGUAGES.filter((l) => l.enabled);

export function languageByCode(code: string): LanguageDef | undefined {
  return LANGUAGES.find((l) => l.code === code);
}

export function scriptFor(code: string): LanguageDef["script"] {
  return languageByCode(code)?.script ?? "latn";
}

export function isLanguageEnabled(code: string): boolean {
  return ENABLED_LANGUAGES.some((l) => l.code === code);
}

/** Region groups for the LanguageSheet, in display order (English has region "all"). */
export const REGION_ORDER: Array<Exclude<LanguageDef["region"], "all">> = [
  "north",
  "west",
  "east",
  "south",
];

export function languagesByRegion(region: LanguageDef["region"]): LanguageDef[] {
  return ENABLED_LANGUAGES.filter((l) => l.region === region);
}

/** Map a browser language tag (e.g. "hi-IN", "ta") to an enabled language code. */
export function browserToEnabledCode(tag: string): string | undefined {
  const t = tag.toLowerCase();
  const exact = ENABLED_LANGUAGES.find((l) => l.code.toLowerCase() === t);
  if (exact) return exact.code;
  const base = t.split("-")[0];
  const byBase = ENABLED_LANGUAGES.find((l) => l.code.toLowerCase().split("-")[0] === base);
  return byBase?.code;
}
