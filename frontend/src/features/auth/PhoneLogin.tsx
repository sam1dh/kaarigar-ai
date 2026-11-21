import {
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IdCard, QrCode } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import LanguageSheet from "@/components/LanguageSheet";
import { ApiError, api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { chooseLanguage } from "@/i18n";
import { languageByCode } from "@/i18n/languages";
import { useSessionStore } from "@/stores/session";
import { cn } from "@/lib/utils";
import type { PinLoginResponse } from "./types";

const PIN_LENGTH = 6;

/** Quick pills per section 7.5: English · हिन्दी · <last chosen if different> · 🌐 More. */
const QUICK_LANGS = [
  { code: "en-IN", label: "English" },
  { code: "hi-IN", label: "हिन्दी" },
];

/** Plant chip from VITE_PLANT_CODE — real plant name shows after login. */
function plantLabel(): string {
  const code = (import.meta.env.VITE_PLANT_CODE as string) || "";
  if (!code) return "";
  const pretty = code.charAt(0).toUpperCase() + code.slice(1);
  return `${pretty} · Pune`;
}

export default function PhoneLogin() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const loadProfile = useSessionStore((s) => s.loadProfile);

  const [lang, setLang] = useState<string>(() => i18n.language);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [pin, setPin] = useState<string[]>(Array(PIN_LENGTH).fill(""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set by lib/api.ts when a deactivated account is signed out mid-session.
  const [notice] = useState<string | null>(() => {
    try {
      const m = sessionStorage.getItem("kaarigar.authNotice");
      sessionStorage.removeItem("kaarigar.authNotice");
      return m;
    } catch {
      return null;
    }
  });
  const pinRefs = useRef<(HTMLInputElement | null)[]>([]);

  const pinValue = useMemo(() => pin.join(""), [pin]);

  /** Shown only when the user's last chosen language isn't already on a pill. */
  const thirdPill = QUICK_LANGS.some((p) => p.code === lang)
    ? null
    : { code: lang, label: languageByCode(lang)?.native ?? lang };

  function setPinAt(index: number, value: string) {
    const digits = value.replace(/\D/g, "");
    setError(null);
    if (digits.length > 1) {
      // Paste support: fill as many boxes as we got digits for.
      setPin((prev) => {
        const next = [...prev];
        for (let i = 0; i < digits.length && index + i < PIN_LENGTH; i++) {
          next[index + i] = digits[i]!;
        }
        return next;
      });
      const target = Math.min(index + digits.length, PIN_LENGTH - 1);
      pinRefs.current[target]?.focus();
      return;
    }
    setPin((prev) => {
      const next = [...prev];
      next[index] = digits;
      return next;
    });
    if (digits && index < PIN_LENGTH - 1) pinRefs.current[index + 1]?.focus();
  }

  function onPinKeyDown(
    index: number,
    e: ReactKeyboardEvent<HTMLInputElement>,
  ) {
    if (e.key === "Backspace" && !pin[index] && index > 0) {
      pinRefs.current[index - 1]?.focus();
      setPinAt(index - 1, "");
    }
  }

  async function pickLanguage(code: string) {
    setLang(code);
    setSheetOpen(false);
    chooseLanguage(code); // switches i18n and is remembered in localStorage
  }

  async function signIn() {
    if (busy) return;
    if (!employeeId.trim() || pinValue.length < PIN_LENGTH) {
      setError(t("login.invalidLogin"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api<PinLoginResponse>("/auth/pin-login", {
        method: "POST",
        body: {
          plant_code: (import.meta.env.VITE_PLANT_CODE as string) || "shree",
          employee_id: employeeId.trim(),
          pin: pinValue,
        },
      });
      await supabase.auth.setSession({
        access_token: res.access_token,
        refresh_token: res.refresh_token,
      });
      await loadProfile();
      navigate("/tech", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        const key =
          err.code === "too_many_attempts"
            ? "login.tooManyAttempts"
            : err.code === "invalid_login"
              ? "login.invalidLogin"
              : "login.networkError"; // server_error / validation → connectivity message
        setError(t(key));
      } else {
        setError(t("login.networkError"));
      }
      // Clear the PIN so a retry starts fresh (test case PL-06).
      setPin(Array(PIN_LENGTH).fill(""));
      pinRefs.current[0]?.focus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[420px] flex-col px-6 pb-8 pt-6">
      {/* Plant chip */}
      {plantLabel() && (
        <div className="mb-8 self-start rounded-full border border-line bg-white px-4 py-2 text-sm font-medium text-green-deep">
          {plantLabel()}
        </div>
      )}

      {/* Wordmark */}
      <div className="mb-6 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full bg-green-deep" />
        <span className="font-head text-xl font-bold text-green-deep">
          {t("login.wordmark")}
        </span>
      </div>

      {/* Heading */}
      <h1 className="font-head text-[2.5rem] font-semibold leading-[1.1] tracking-tight text-ink">
        {t("login.heading")}
      </h1>
      <p className="mt-3 text-[0.9375rem] text-ink-muted">{t("login.subline")}</p>
      {notice && (
        <p className="mt-4 rounded-xl bg-alert/10 px-4 py-3 text-sm font-medium text-alert">
          {notice}
        </p>
      )}

      {/* Language pills: English · हिन्दी · <last chosen if different> · 🌐 More */}
      <div className="mt-8">
        <p className="mb-3 text-sm font-medium text-ink-muted">
          {t("login.languageLabel")}
        </p>
        <div className="flex flex-wrap gap-2">
          {/* English · हिन्दी · <last chosen if different> */}
          {QUICK_LANGS.map((p) => (
            <button
              key={p.code}
              type="button"
              onClick={() => void pickLanguage(p.code)}
              className={cn(
                "rounded-full px-4 py-2.5 text-sm font-semibold transition-colors",
                lang === p.code
                  ? "bg-green-deep text-white"
                  : "border border-line bg-white text-ink hover:bg-surface",
              )}
            >
              {p.label}
            </button>
          ))}
          {thirdPill && (
            <button
              type="button"
              onClick={() => void pickLanguage(thirdPill.code)}
              className="break-words rounded-full bg-green-deep px-4 py-2.5 text-sm font-semibold text-white transition-colors"
            >
              {thirdPill.label}
            </button>
          )}
          {/* 🌐 More */}
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-label={t("sheet.title")}
            className={cn(
              "flex items-center gap-1.5 rounded-full border border-line bg-white px-4 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-surface",
              thirdPill && "break-words",
            )}
          >
            🌐 {t("sheet.more")}
          </button>
        </div>
      </div>

      {/* Employee ID */}
      <div className="mt-8">
        <label
          htmlFor="employee-id"
          className="mb-2 block text-sm font-medium text-ink-muted"
        >
          {t("login.employeeIdLabel")}
        </label>
        <div className="relative">
          <IdCard className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
          <Input
            id="employee-id"
            value={employeeId}
            onChange={(e) => {
              setEmployeeId(e.target.value.toUpperCase());
              setError(null);
            }}
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            placeholder={t("login.employeeIdPlaceholder")}
            className="pl-12 font-medium"
          />
        </div>
      </div>

      {/* 6-digit PIN */}
      <div className="mt-6">
        <p className="mb-2 text-sm font-medium text-ink-muted">
          {t("login.pinLabel")}
        </p>
        <div className="flex gap-2" onPaste={(e) => e.preventDefault()}>
          {pin.map((digit, i) => (
            <input
              key={i}
              ref={(el) => {
                pinRefs.current[i] = el;
              }}
              value={digit}
              inputMode="numeric"
              autoComplete={i === 0 ? "one-time-code" : "off"}
              maxLength={PIN_LENGTH}
              onChange={(e) => setPinAt(i, e.target.value)}
              onKeyDown={(e) => onPinKeyDown(i, e)}
              onFocus={(e) => e.target.select()}
              aria-label={`${t("login.pinLabel")} ${i + 1}`}
              className="h-[62px] w-full rounded-[14px] border border-line bg-white text-center text-2xl font-semibold text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green"
            />
          ))}
        </div>
      </div>

      {error && <p className="mt-4 text-sm font-medium text-alert">{error}</p>}

      {/* Actions */}
      <div className="mt-8 flex flex-col gap-3">
        <Button size="tall" onClick={() => void signIn()} disabled={busy}>
          {busy ? t("login.signingIn") : t("login.signIn")}
        </Button>
        <Button
          variant="outline"
          size="tall"
          className="font-semibold"
          onClick={() => toast(t("login.comingSoon"))}
        >
          <QrCode className="h-5 w-5" />
          {t("login.scanBadge")}
        </Button>
      </div>

      <p className="mt-6 text-center text-sm text-ink-muted">
        {t("login.forgotPin")}
      </p>

      <LanguageSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        current={lang}
        onPick={pickLanguage}
      />
    </div>
  );
}
