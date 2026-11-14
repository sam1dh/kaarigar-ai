import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Eye, EyeOff, Lock, Mail, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { supabase } from "@/lib/supabase";
import { homeForRole, useSessionStore } from "@/stores/session";

/** Split screen: brand panel (left) + sign-in card (right). Desktop only. */
export default function WebLogin() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const loadProfile = useSessionStore((s) => s.loadProfile);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    if (busy) return;
    if (!email.trim() || !password) {
      setError("Enter your work email and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (authError) {
        setError("Wrong email or password. Please try again.");
        return;
      }
      const profile = await loadProfile();
      navigate(profile ? homeForRole(profile.role) : "/manager/login", {
        replace: true,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Brand panel */}
      <div className="hidden w-1/2 flex-col justify-between bg-green-deep p-12 text-white lg:flex">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-white" />
          <span className="font-head text-xl font-bold">Kaarigar</span>
        </div>

        <div className="max-w-xl">
          <h1 className="font-head text-[44px] font-semibold leading-[1.1] tracking-tight">
            Every fix your experts make, ready for the next shift.
          </h1>
          <p className="mt-4 text-lg text-white/80">
            Review repairs, answer escalations and keep your plant's know-how in
            one place.
          </p>
        </div>

        <p className="text-sm text-white/70">
          Shree Hydraulics · Pune · 24 machines
        </p>
      </div>

      {/* Sign-in card */}
      <div className="flex w-full flex-col items-center justify-center bg-enamel px-6 lg:w-1/2">
        <div className="w-full max-w-md rounded-card bg-white p-8 shadow-sm">
          <h1 className="font-head text-3xl font-semibold text-ink">
            {t("login.signIn")}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            For supervisors and admins
          </p>

          <div className="mt-8">
            <label
              htmlFor="work-email"
              className="mb-2 block text-sm font-medium text-ink-muted"
            >
              Work email
            </label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
              <Input
                id="work-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="suresh@shreehydraulics.in"
                className="pl-12"
                autoComplete="email"
              />
            </div>
          </div>

          <div className="mt-5">
            <div className="mb-2 flex items-baseline justify-between">
              <label
                htmlFor="password"
                className="text-sm font-medium text-ink-muted"
              >
                Password
              </label>
              <button
                type="button"
                className="text-sm font-medium text-green hover:underline"
              >
                Forgot password?
              </button>
            </div>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="pl-12 pr-12"
                autoComplete="current-password"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void signIn();
                }}
              />
              <button
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink"
              >
                {showPassword ? (
                  <EyeOff className="h-5 w-5" />
                ) : (
                  <Eye className="h-5 w-5" />
                )}
              </button>
            </div>
          </div>

          {error && (
            <p className="mt-4 text-sm font-medium text-alert">{error}</p>
          )}

          <Button
            size="tall"
            className="mt-7 w-full"
            onClick={() => void signIn()}
            disabled={busy}
          >
            {busy ? t("login.signingIn") : t("login.signIn")}
          </Button>

          <Separator className="my-6" />

          <div className="flex items-start gap-3 text-sm text-ink-muted">
            <Smartphone className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <p>
              Technician? Open Kaarigar on your phone and sign in with your
              employee ID and PIN.
            </p>
          </div>
        </div>

        <p className="mt-6 flex items-center gap-2 text-sm text-ink-muted">
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-green-tint text-[10px] font-bold text-green-deep">
            ✓
          </span>
          Role-based access · your plant's data stays in your workspace
        </p>
      </div>
    </div>
  );
}
