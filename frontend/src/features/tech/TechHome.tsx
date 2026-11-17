import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Globe, LogOut, Search, Type } from "lucide-react";
import { Link } from "react-router-dom";
import MyNotes from "@/features/capture/MyNotes";
import { Input } from "@/components/ui/input";
import LanguageSheet from "@/components/LanguageSheet";
import TextSizeControl from "@/components/TextSizeControl";
import { api } from "@/lib/api";
import { initials } from "@/features/auth/types";
import type { Machine } from "@/features/auth/types";
import { useSessionStore } from "@/stores/session";

/** /tech — the technician's home screen (mobile-first, per technician-pwa.pdf Home). */
export default function TechHome() {
  const { t } = useTranslation();
  const profile = useSessionStore((s) => s.profile);
  const signOut = useSessionStore((s) => s.signOut);
  const setLanguage = useSessionStore((s) => s.setLanguage);
  const [menuOpen, setMenuOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [sizeOpen, setSizeOpen] = useState(false);
  const [codeFilter, setCodeFilter] = useState("");

  const { data: machines, isLoading } = useQuery({
    queryKey: ["tech", "machines"],
    queryFn: () => api<Machine[]>("/tech/machines"),
  });

  const filtered = (machines ?? []).filter(
    (m) =>
      !codeFilter.trim() ||
      m.code.toLowerCase().includes(codeFilter.trim().toLowerCase()),
  );

  function greeting() {
    const hour = new Date().getHours();
    if (hour >= 17)
      return t("tech.greetingEvening", { name: firstName(profile?.name) });
    if (hour >= 12)
      return t("tech.greetingAfternoon", { name: firstName(profile?.name) });
    return t("tech.greetingMorning", { name: firstName(profile?.name) });
  }

  function firstName(name: string | undefined) {
    return name?.split(/\s+/)[0] ?? "";
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[480px] flex-col px-5 pb-10 pt-5">
      {/* Header: wordmark + avatar */}
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-green-deep" />
          <span className="font-head text-xl font-bold text-green-deep">
            {t("login.wordmark")}
          </span>
        </div>
        <div className="relative">
          <button
            type="button"
            aria-label="Account menu"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-green-tint text-sm font-bold text-green-deep"
          >
            {initials(profile?.name ?? "")}
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-12 z-20 w-52 overflow-hidden rounded-xl border border-line bg-white py-1 shadow-lg">
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  setLangOpen(true);
                }}
                className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-ink hover:bg-surface"
              >
                <Globe className="h-4 w-4" />
                {t("sheet.title")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  setSizeOpen(true);
                }}
                className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-ink hover:bg-surface"
              >
                <Type className="h-4 w-4" />
                {t("textSize.title")}
              </button>
              <button
                type="button"
                onClick={() => void signOut()}
                className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-ink hover:bg-surface"
              >
                <LogOut className="h-4 w-4" />
                {t("tech.signOut")}
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Greeting + heading */}
      <p className="mt-8 text-[0.9375rem] text-ink-muted">{greeting()}</p>
      <h1 className="mt-1 font-head text-[2.125rem] font-semibold leading-[1.15] tracking-tight text-ink">
        {t("tech.whichMachine")}
      </h1>

      {/* Dark green QR placeholder card (camera arrives in a later phase) */}
      <div className="mt-6 flex flex-col items-center rounded-card bg-green-deep px-6 py-10 text-white">
        <div className="relative mb-6 flex h-28 w-28 items-center justify-center">
          {/* corner brackets */}
          {[
            "top-0 left-0 border-t-2 border-l-2 rounded-tl-lg",
            "top-0 right-0 border-t-2 border-r-2 rounded-tr-lg",
            "bottom-0 left-0 border-b-2 border-l-2 rounded-bl-lg",
            "bottom-0 right-0 border-b-2 border-r-2 rounded-br-lg",
          ].map((pos) => (
            <span
              key={pos}
              className={`absolute h-8 w-8 border-white/80 ${pos}`}
            />
          ))}
          {/* faux QR dots */}
          <div className="grid grid-cols-4 gap-1 opacity-60">
            {Array.from({ length: 16 }).map((_, i) => (
              <span
                key={i}
                className={`h-2 w-2 rounded-[2px] ${i % 3 === 0 ? "bg-white" : "bg-white/30"}`}
              />
            ))}
          </div>
        </div>
        <p className="text-center text-[0.9375rem] text-white/85">
          {t("tech.scanQr")}
        </p>
      </div>

      {/* Type a machine code */}
      <div className="relative mt-4">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
        <Input
          value={codeFilter}
          onChange={(e) => setCodeFilter(e.target.value)}
          placeholder={t("tech.orTypeCode")}
          className="pl-12"
          inputMode="search"
        />
      </div>

      {/* Machine list */}
      <p className="mb-3 mt-8 text-sm font-medium text-ink-muted">
        {t("tech.allMachines")}
      </p>
      {isLoading ? (
        <div className="rounded-card border border-line bg-white p-5 text-sm text-ink-muted">
          …
        </div>
      ) : !filtered.length ? (
        <div className="rounded-card border border-line bg-white p-5 text-sm text-ink-muted">
          {t("tech.noMachines")}
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-line bg-white">
          {filtered.map((m, i) => (
            <Link
              key={m.id}
              to={`/tech/machines/${encodeURIComponent(m.code)}`}
              className={`flex w-full items-center gap-4 px-4 py-4 text-left hover:bg-surface ${
                i > 0 ? "border-t border-line" : ""
              }`}
            >
              <span className="rounded-xl bg-enamel px-3 py-2 font-head text-sm font-bold text-ink">
                {m.code}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-ink">
                  {m.name || m.code}
                </span>
                <span className="block truncate text-sm text-ink-muted">
                  {m.line}
                </span>
              </span>
              <ChevronRight className="h-5 w-5 shrink-0 text-ink-faint" />
            </Link>
          ))}
        </div>
      )}

      {/* Experts and supervisors can find their own recordings here. */}
      {(profile?.role === "expert" || profile?.role === "supervisor") && (
        <>
          <p className="mb-3 mt-8 text-sm font-medium text-ink-muted">
            {t("capture.myNotes.onThisMachine")}
          </p>
          <MyNotes limit={5} />
        </>
      )}

      <LanguageSheet
        open={langOpen}
        onClose={() => setLangOpen(false)}
        current={profile?.language ?? "en-IN"}
        onPick={async (code) => {
          await setLanguage(code);
          setLangOpen(false);
        }}
      />
      <TextSizeControl open={sizeOpen} onClose={() => setSizeOpen(false)} />
    </div>
  );
}
