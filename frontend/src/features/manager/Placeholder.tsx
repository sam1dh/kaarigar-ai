import { useTranslation } from "react-i18next";
import { Hammer } from "lucide-react";

/** Placeholder for nav items whose real screens arrive in later phases. */
export default function Placeholder({
  phase,
  title,
}: {
  phase: string;
  title?: string;
}) {
  const { t } = useTranslation();

  return (
    <div className="max-w-3xl">
      <h1 className="font-head text-[2rem] font-semibold tracking-tight text-ink">
        {title ?? ""}
      </h1>
      <div className="mt-10 flex flex-col items-center justify-center rounded-card border border-line bg-white px-10 py-16 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-history-tint">
          <Hammer className="h-6 w-6 text-history" />
        </span>
        <p className="mt-5 text-lg font-semibold text-ink">
          {t("manager.comingInPhase", { phase })}
        </p>
      </div>
    </div>
  );
}
