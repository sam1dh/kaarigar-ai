import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import { applyTextSize, type TextSizeValue } from "@/i18n";
import { cn } from "@/lib/utils";

interface TextSizeControlProps {
  open: boolean;
  onClose: () => void;
}

const OPTIONS: Array<{
  value: TextSizeValue;
  labelKey: string;
  percent: string;
}> = [
  { value: "normal", labelKey: "textSize.normal", percent: "100%" },
  { value: "large", labelKey: "textSize.large", percent: "115%" },
  { value: "xlarge", labelKey: "textSize.extra", percent: "130%" },
];

/**
 * Text size picker (section 7.5): Normal 100% / Large 115% / Extra large
 * 130%, applied via <html data-text-size> and remembered in
 * localStorage "kaarigar.textSize".
 */
export default function TextSizeControl({ open, onClose }: TextSizeControlProps) {
  const { t, i18n } = useTranslation();
  const current = (document.documentElement.dataset.textSize as
    | TextSizeValue
    | undefined) ?? "normal";

  // Escape closes; re-render when the sheet opens so `current` is fresh.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function pick(size: TextSizeValue) {
    applyTextSize(size);
    i18n.emit("languageChanged"); // re-render so the tick moves
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={t("textSize.title")}
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
        tabIndex={-1}
      />

      <div className="relative w-full max-w-md rounded-t-[28px] bg-white px-5 pb-8 pt-5 shadow-xl sm:rounded-[28px] sm:pb-5">
        <div className="mx-auto mb-4 h-1.5 w-10 rounded-full bg-line sm:hidden" />

        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-head text-xl font-semibold text-ink">
            {t("textSize.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-3 py-1.5 text-sm font-medium text-green hover:bg-green-tint"
          >
            {t("sheet.done")}
          </button>
        </div>

        <div className="flex flex-col gap-2">
          {OPTIONS.map((o) => {
            const active = o.value === current;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => pick(o.value)}
                aria-pressed={active}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded-2xl border px-4 py-3.5 text-left transition-colors",
                  active
                    ? "border-green bg-green-tint"
                    : "border-line bg-white hover:bg-surface",
                )}
              >
                <span className="font-semibold text-ink">
                  {t(o.labelKey)}
                </span>
                <span className="flex items-center gap-3 text-sm text-ink-muted">
                  {o.percent}
                  {active && <Check className="h-5 w-5 text-green" />}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
