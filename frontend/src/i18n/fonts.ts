/**
 * Per-script font loading (PHASE_0.md section 7.5).
 *
 * Only Anek Latin + IBM Plex Sans download at app start (imported eagerly in
 * main.tsx). Every other script's fonts download on demand, once, via dynamic
 * imports — then the PWA caches them. Family names below must match what the
 * installed @fontsource-variable packages register ("… Variable").
 */
import type { LanguageDef } from "./languages";

const FONT_IMPORTS: Partial<Record<LanguageDef["script"], { heading: () => Promise<unknown>; body: () => Promise<unknown> }>> = {
  latn: {
    heading: () => import("@fontsource-variable/anek-latin"),
    body: () => import("@fontsource-variable/ibm-plex-sans"),
  },
  deva: {
    heading: () => import("@fontsource-variable/anek-devanagari"),
    // No variable build exists — static @fontsource package.
    body: () => import("@fontsource/ibm-plex-sans-devanagari/500.css"),
  },
  guru: {
    heading: () => import("@fontsource-variable/anek-gurmukhi"),
    body: () => import("@fontsource-variable/noto-sans-gurmukhi"),
  },
  gujr: {
    heading: () => import("@fontsource-variable/anek-gujarati"),
    body: () => import("@fontsource-variable/noto-sans-gujarati"),
  },
  beng: {
    heading: () => import("@fontsource-variable/anek-bangla"),
    body: () => import("@fontsource-variable/noto-sans-bengali"),
  },
  orya: {
    heading: () => import("@fontsource-variable/anek-odia"),
    body: () => import("@fontsource-variable/noto-sans-oriya"),
  },
  taml: {
    heading: () => import("@fontsource-variable/anek-tamil"),
    body: () => import("@fontsource-variable/noto-sans-tamil"),
  },
  telu: {
    heading: () => import("@fontsource-variable/anek-telugu"),
    body: () => import("@fontsource-variable/noto-sans-telugu"),
  },
  knda: {
    heading: () => import("@fontsource-variable/anek-kannada"),
    body: () => import("@fontsource-variable/noto-sans-kannada"),
  },
  mlym: {
    heading: () => import("@fontsource-variable/anek-malayalam"),
    body: () => import("@fontsource-variable/noto-sans-malayalam"),
  },
};

const loaded = new Set<LanguageDef["script"]>();

/** Download the heading + body font for a script. Idempotent. */
export async function loadScriptFonts(script: LanguageDef["script"]): Promise<void> {
  if (loaded.has(script)) return;
  const pair = FONT_IMPORTS[script];
  if (!pair) return;
  await Promise.all([pair.heading(), pair.body()]);
  loaded.add(script);
}
