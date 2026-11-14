import { create } from "zustand";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Profile } from "@/features/auth/types";
import { applyLanguage } from "@/i18n";
import { isLanguageEnabled } from "@/i18n/languages";

/** Where each role should land after sign-in. */
export function homeForRole(role: string | undefined): string {
  return role === "supervisor" ? "/manager" : "/tech";
}

interface SessionState {
  profile: Profile | null;
  /** true until the initial session check finishes */
  loading: boolean;
  loadProfile: () => Promise<Profile | null>;
  setProfile: (p: Profile | null) => void;
  /** Signed-in language change: PATCH /auth/me, then switch the UI. */
  setLanguage: (code: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export const useSessionStore = create<SessionState>((set) => ({
  profile: null,
  loading: true,

  /** Reads the Supabase session and fetches /auth/me. Safe to call when logged out. */
  loadProfile: async () => {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      set({ profile: null, loading: false });
      return null;
    }
    try {
      const profile = await api<Profile>("/auth/me");
      set({ profile, loading: false });
      // The user's language wins after login (PHASE_0.md section 6).
      if (isLanguageEnabled(profile.language)) {
        await applyLanguage(profile.language);
      }
      return profile;
    } catch {
      // Session exists but no valid profile → force a clean re-login.
      await supabase.auth.signOut();
      set({ profile: null, loading: false });
      return null;
    }
  },

  setProfile: (profile) => set({ profile }),

  setLanguage: async (code) => {
    const profile = await api<Profile>("/auth/me", {
      method: "PATCH",
      body: { language: code },
    });
    set({ profile });
    await applyLanguage(code);
  },

  signOut: async () => {
    await supabase.auth.signOut();
    set({ profile: null, loading: false });
  },
}));
