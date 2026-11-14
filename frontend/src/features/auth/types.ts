/** Profile returned by GET /auth/me. */
export interface Profile {
  id: string;
  name: string;
  employee_id: string | null;
  role: "technician" | "expert" | "supervisor";
  is_admin: boolean;
  language: string;
  tenant: {
    id: string;
    name: string;
    slug: string;
  };
}

/** Machines for TechHome, from GET /tech/machines. */
export interface Machine {
  id: string;
  code: string;
  name: string | null;
  line: string | null;
  model: string | null;
}

/** Response of POST /auth/pin-login. */
export interface PinLoginResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  profile: Profile;
}

/** Initials for avatar bubbles: "Amit Kale" → "AK". */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}
