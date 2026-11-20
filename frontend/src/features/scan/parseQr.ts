/**
 * What a scanned QR means for Kaarigar. Pure function, no network.
 *
 * - A Kaarigar sticker:  https://<any host>/m/<token>   (token: 8–64 letters/digits, Phase 4 prints 24 hex)
 *   Any host is accepted on purpose, so a sticker printed for dev still opens on app (and the other way round);
 *   the backend only finds the token inside the signed-in person's plant.
 * - A machine code typed or printed as text: "HP-07", "hp 7", "CNC-03".
 * - Anything else (a Wi-Fi QR, a payment QR, some website): unknown. We NEVER open a scanned URL.
 */
export type QrTarget =
  | { kind: 'token'; token: string }
  | { kind: 'code'; code: string }
  | { kind: 'unknown' };

const TOKEN = /^[A-Za-z0-9]{8,64}$/;
const CODE = /^[A-Z]{1,6}-?\d{1,4}[A-Z]?$/;

/** Same rule as the backend (Phase 4 normalize_code): "hp 07" → "HP-07". */
export function normalizeCode(raw: string): string {
  return raw.trim().toUpperCase().replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

export function parseMachineQr(raw: string): QrTarget {
  const s = (raw ?? '').trim();
  if (!s || s.length > 512) return { kind: 'unknown' };

  if (/^https?:\/\//i.test(s)) {
    let url: URL;
    try {
      url = new URL(s);
    } catch {
      return { kind: 'unknown' };
    }
    const m = url.pathname.match(/^\/m\/([^/]+)\/?$/);
    return m && TOKEN.test(m[1]) ? { kind: 'token', token: m[1] } : { kind: 'unknown' };
  }

  const path = s.match(/^\/?m\/([A-Za-z0-9]{8,64})\/?$/);
  if (path) return { kind: 'token', token: path[1] };

  const code = normalizeCode(s);
  if (CODE.test(code)) return { kind: 'code', code };
  return { kind: 'unknown' };
}
