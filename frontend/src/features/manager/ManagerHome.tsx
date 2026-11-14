import { useTranslation } from "react-i18next";
import { Inbox } from "lucide-react";

/** /manager — Review queue placeholder (queue logic arrives in Phase 3). */
export default function ManagerHome() {
  const { t } = useTranslation();

  return (
    <div className="max-w-3xl">
      <h1 className="font-head text-[32px] font-semibold tracking-tight text-ink">
        {t("manager.reviewQueue")}
      </h1>
      <div className="mt-10 flex flex-col items-center justify-center rounded-card border border-line bg-white px-10 py-16 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-green-tint">
          <Inbox className="h-6 w-6 text-green-deep" />
        </span>
        <p className="mt-5 text-lg font-semibold text-ink">
          {t("manager.emptyTitle")}
        </p>
        <p className="mt-2 max-w-sm text-sm text-ink-muted">
          {t("manager.emptyBody")}
        </p>
      </div>
    </div>
  );
}
