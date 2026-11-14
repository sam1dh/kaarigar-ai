import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import {
  ENABLED_LANGUAGES,
  REGION_ORDER,
  languageByCode,
  type LanguageDef,
} from "@/i18n/languages";
import { cn } from "@/lib/utils";

interface LanguageSheetProps {
  open: boolean;
  onClose: () => void;
  /** Currently active language code */
  current: string;
  /** Called with the chosen code — caller decides whether to persist it. */
  onPick: (code: string) => void | Promise<void>;
}

/**
 * Language picker (section 7.5): bottom sheet on the phone, centered dialog
 * on the web. Shows only ENABLED languages, grouped North / West / East /
 * South with English on top. Tiles use system fonts so the sheet never has
 * to download every script's fonts just to be shown.
 */
export default function LanguageSheet({
  open,
  onClose,
  current,
  onPick,
}: LanguageSheetProps) {
  const { t } = useTranslation();

  // Escape closes the sheet.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const english = ENABLED_LANGUAGES.filter((l) => l.region === "all");
  const groups = REGION_ORDER.map((region) => ({
    region,
    label: t(`sheet.${region}`),
    items: ENABLED_LANGUAGES.filter((l) => l.region === region),
  })).filter((g) => g.items.length > 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={t("sheet.title")}
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
        tabIndex={-1}
      />

      {/* Panel: bottom sheet on phones, dialog on desktop */}
      <div className="relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-[28px] bg-white px-5 pb-8 pt-5 shadow-xl sm:rounded-[28px] sm:pb-5">
        {/* Grabber (phone) */}
        <div className="mx-auto mb-4 h-1.5 w-10 rounded-full bg-line sm:hidden" />

        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-head text-xl font-semibold text-ink">
            {t("sheet.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-3 py-1.5 text-sm font-medium text-green hover:bg-green-tint"
          >
            {t("sheet.done")}
          </button>
        </div>

        {english.map((l) => (
          <Tile key={l.code} lang={l} current={current} onPick={onPick} />
        ))}

        {groups.map((g) => (
          <section key={g.region} className="mt-2">
            <p className="mb-1 mt-3 px-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              {g.label}
            </p>
            <div className="grid grid-cols-2 gap-2">
              {g.items.map((l) => (
                <Tile
                  key={l.code}
                  lang={l}
                  current={current}
                  onPick={onPick}
                  compact
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function Tile({
  lang,
  current,
  onPick,
  compact = false,
}: {
  lang: LanguageDef;
  current: string;
  onPick: (code: string) => void | Promise<void>;
  compact?: boolean;
}) {
  const active = lang.code === current;
  const englishName = languageByCode(lang.code)?.name ?? lang.name;

  return (
    <button
      type="button"
      onClick={() => void onPick(lang.code)}
      aria-pressed={active}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-2xl border px-4 py-3 text-left transition-colors",
        active
          ? "border-green bg-green-tint"
          : "border-line bg-white hover:bg-surface",
        compact ? "min-w-0" : "",
      )}
    >
      {/* Native name big + English name small; system fonts (no font-body class) */}
      <span className="min-w-0">
        <span
          className={cn(
            "block font-semibold text-ink break-words",
            compact ? "text-base leading-snug" : "text-lg leading-snug",
          )}
        >
          {lang.native}
        </span>
        <span className="block truncate text-xs text-ink-muted">
          {englishName}
        </span>
      </span>
      {active && <Check className="h-5 w-5 shrink-0 text-green" />}
    </button>
  );
}
