import { create } from "zustand";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Profile } from "@/features/auth/types";
import { setAppLanguage } from "@/i18n";

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
      setAppLanguage(profile.language); // default language follows the profile
      return profile;
    } catch {
      // Session exists but no valid profile → force a clean re-login.
      await supabase.auth.signOut();
      set({ profile: null, loading: false });
      return null;
    }
  },

  setProfile: (profile) => set({ profile }),

  signOut: async () => {
    await supabase.auth.signOut();
    set({ profile: null, loading: false });
  },
}));
