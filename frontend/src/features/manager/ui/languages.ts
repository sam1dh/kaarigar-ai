/** Enabled languages from the single list (Phase 0's shared/languages.json).
 *  ADAPT: if Phase 0's lib/languages.ts already exports this list, import it from there instead. */
import data from '../../../../../shared/languages.json';

export interface Lang { code: string; name: string; native: string }
export const LANGUAGES: Lang[] = (data.languages as (Lang & { enabled: boolean })[])
  .filter((l) => l.enabled)
  .map(({ code, name, native }) => ({ code, name, native }));
export const langName = (code: string | null | undefined) => LANGUAGES.find((l) => l.code === code)?.name ?? code ?? '';
