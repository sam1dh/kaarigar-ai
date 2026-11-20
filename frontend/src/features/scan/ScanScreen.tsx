/**
 * /tech/scan — scan a machine's QR sticker from inside the app (TechHome "Scan machine QR").
 *
 * Why in-app and not the phone's camera app: the camera app opens the link in the browser, which on iPhone (and on
 * Android when the app wasn't installed as a WebAPK) is a different session — the technician lands on a login screen.
 * Here the camera runs inside Kaarigar, so the session, language and machine screen are all already there.
 *
 * Camera: qr-scanner (uses the phone's built-in BarcodeDetector on Android Chrome, its own decoder elsewhere).
 * Needs HTTPS (or localhost): the dev tunnel and app.kaarigar-ai.online are fine, http://192.168.x.x is not.
 * A scanned URL is never opened: only /m/<token> is read, and the token is looked up for the signed-in plant.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import type QrScannerType from 'qr-scanner';
import { getMachine, machineByQr, type MachineRef } from '../assist/assistApi';
import { errorCode } from '../capture/captureApi';
import { parseMachineQr, type QrTarget } from './parseQr';

type Phase = 'starting' | 'scanning' | 'checking' | 'found';
type Problem = null | 'permission' | 'no_camera' | 'insecure' | 'camera_failed';
type Toast = null | { tone: 'alert' | 'info'; text: string };

const SAME_QR_PAUSE_MS = 4000;   // after a wrong sticker, ignore the same QR for a moment so the message can be read

export async function lookUpTarget(target: QrTarget): Promise<MachineRef> {
  if (target.kind === 'token') return machineByQr(target.token);
  if (target.kind === 'code') return getMachine(target.code);
  throw Object.assign(new Error('not a sticker'), { code: 'not_kaarigar' });
}

/** qr-scanner reports every getUserMedia failure as "Camera not found.", so ask the Permissions API what really happened. */
async function whyCameraFailed(err: unknown): Promise<Problem> {
  try {
    const st = await navigator.permissions?.query({ name: 'camera' as PermissionName });
    if (st?.state === 'denied') return 'permission';
  } catch { /* Permissions API not available (older Safari) */ }
  return cameraProblem(err);
}

function cameraProblem(err: unknown): Problem {
  const s = String((err as { name?: string })?.name ?? err ?? '');
  if (/NotAllowed|Permission|denied/i.test(s)) return 'permission';
  if (/NotFound|Camera not found|no camera|OverconstrainedError/i.test(s)) return 'no_camera';
  return 'camera_failed';
}

export default function ScanScreen() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const videoRef = useRef<HTMLVideoElement>(null);
  const scannerRef = useRef<QrScannerType | null>(null);
  const busyRef = useRef(false);
  const lastBadRef = useRef<{ text: string; at: number } | null>(null);
  const [phase, setPhase] = useState<Phase>('starting');
  const [problem, setProblem] = useState<Problem>(null);
  const [toast, setToast] = useState<Toast>(null);
  const [torch, setTorch] = useState<{ available: boolean; on: boolean }>({ available: false, on: false });
  const [typing, setTyping] = useState(false);
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState<string | null>(null);

  const open = useCallback(async (target: QrTarget, raw: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setPhase('checking');
    setToast(null);
    try {
      const m = await lookUpTarget(target);
      setPhase('found');
      try { navigator.vibrate?.(60); } catch { /* not supported */ }
      scannerRef.current?.stop();
      nav(`/tech/machines/${encodeURIComponent(m.code)}`, { replace: true });
    } catch (e) {
      const c = errorCode(e);
      lastBadRef.current = { text: raw, at: Date.now() };
      setToast({
        tone: 'alert',
        text: c === 'not_kaarigar' ? t('scan.notKaarigar')
          : c === 'machine_not_found' || c === 'not_found' ? t('scan.notInPlant')
          : c === 'network' ? t('scan.offline') : t('scan.lookupFailed'),
      });
      setPhase('scanning');
      busyRef.current = false;
    }
  }, [nav, t]);

  useEffect(() => {
    if (!window.isSecureContext) { setProblem('insecure'); return; }
    let cancelled = false;
    let scanner: QrScannerType | null = null;
    (async () => {
      const { default: QrScanner } = await import('qr-scanner');
      if (cancelled || !videoRef.current) return;
      scanner = new QrScanner(videoRef.current, (result) => {
        const raw = result.data;
        const bad = lastBadRef.current;
        if (busyRef.current || (bad && bad.text === raw && Date.now() - bad.at < SAME_QR_PAUSE_MS)) return;
        const target = parseMachineQr(raw);
        if (target.kind === 'unknown') {
          lastBadRef.current = { text: raw, at: Date.now() };
          setToast({ tone: 'alert', text: t('scan.notKaarigar') });
          return;
        }
        void open(target, raw);
      }, { returnDetailedScanResult: true, preferredCamera: 'environment', maxScansPerSecond: 8, highlightScanRegion: false, highlightCodeOutline: false });
      scannerRef.current = scanner;
      try {
        await scanner.start();
        if (cancelled) return;
        setPhase('scanning');
        setTorch({ available: await scanner.hasFlash(), on: false });
      } catch (err) {
        const why = await whyCameraFailed(err);
        if (!cancelled) setProblem(why);
      }
    })().catch(async (err) => { const why = await whyCameraFailed(err); if (!cancelled) setProblem(why); });

    const onVisibility = () => {                         // save battery: camera off while the app is in the background
      if (!scanner) return;
      if (document.hidden) scanner.stop();
      else if (!busyRef.current) void scanner.start().catch(() => undefined);
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibility);
      scanner?.destroy();
      scannerRef.current = null;
    };
  }, [open, t]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(id);
  }, [toast]);

  const toggleTorch = async () => {
    const s = scannerRef.current;
    if (!s) return;
    try {
      await s.toggleFlash();
      setTorch({ available: true, on: s.isFlashOn() });
    } catch { setTorch({ available: false, on: false }); }
  };

  const submitCode = async () => {
    const target = parseMachineQr(code);
    if (target.kind !== 'code') { setCodeError(t('scan.badCode')); return; }
    setCodeError(null);
    try {
      const m = await getMachine(target.code);
      nav(`/tech/machines/${encodeURIComponent(m.code)}`, { replace: true });
    } catch (e) {
      setCodeError(errorCode(e) === 'network' ? t('scan.offline') : t('scan.codeNotFound', { code: target.code }));
    }
  };

  const problemText = problem && t(`scan.problem.${problem}`);

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-[#0F1716] text-white" style={{ fontFamily: 'var(--font-body)' }}>
      {/* top bar */}
      <div className="relative z-10 flex items-center gap-3 px-4 pb-3 pt-[max(12px,env(safe-area-inset-top))]">
        <button type="button" onClick={() => nav(-1)} aria-label={t('scan.back')}
          className="grid h-11 w-11 place-items-center rounded-full bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M15 18l-6-6 6-6" /></svg>
        </button>
        <h1 className="flex-1 text-lg font-semibold" style={{ fontFamily: 'var(--font-heading)' }}>{t('scan.title')}</h1>
        {torch.available && (
          <button type="button" onClick={toggleTorch} aria-pressed={torch.on} aria-label={t(torch.on ? 'scan.torchOff' : 'scan.torchOn')}
            className={`grid h-11 w-11 place-items-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white ${torch.on ? 'bg-[var(--safety)] text-[var(--ink)]' : 'bg-white/10'}`}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M7 2h10v4l-3 4v12h-4V10L7 6z" /></svg>
          </button>
        )}
      </div>

      {/* camera */}
      <div className="relative flex-1 overflow-hidden">
        <video ref={videoRef} className="absolute inset-0 h-full w-full object-cover" muted playsInline aria-hidden />
        {!problem && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center" aria-hidden>
            <div className="relative h-[68vw] max-h-[320px] w-[68vw] max-w-[320px] rounded-[28px] shadow-[0_0_0_100vmax_rgba(15,23,22,0.55)]">
              {['left-0 top-0 border-l-4 border-t-4 rounded-tl-[28px]', 'right-0 top-0 border-r-4 border-t-4 rounded-tr-[28px]',
                'bottom-0 left-0 border-b-4 border-l-4 rounded-bl-[28px]', 'bottom-0 right-0 border-b-4 border-r-4 rounded-br-[28px]'].map((c) => (
                <span key={c} className={`absolute h-12 w-12 ${phase === 'found' || phase === 'checking' ? 'border-[#7BD3A8]' : 'border-white'} ${c}`} />
              ))}
            </div>
          </div>
        )}
        {problem && (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div role="alert" className="max-w-[340px] rounded-[22px] bg-white p-5 text-[var(--ink)]">
              <p className="font-semibold leading-snug">{problemText}</p>
              {problem === 'permission' && <p className="mt-2 text-sm text-[var(--ink-muted)]">{t('scan.problem.permissionHow')}</p>}
            </div>
          </div>
        )}
        {toast && (
          <div role="status" aria-live="assertive" className={`absolute inset-x-4 top-3 rounded-2xl px-4 py-3 text-[15px] font-semibold ${toast.tone === 'alert' ? 'bg-[var(--alert-tint)] text-[var(--alert)]' : 'bg-white text-[var(--ink)]'}`}>
            {toast.text}
          </div>
        )}
      </div>

      {/* bottom */}
      <div className="relative z-10 space-y-3 px-4 pb-[max(20px,env(safe-area-inset-bottom))] pt-4">
        <p aria-live="polite" className="text-center text-[15px] text-white/85">
          {phase === 'starting' && !problem ? t('scan.starting') : phase === 'checking' || phase === 'found' ? t('scan.opening') : !problem ? t('scan.hint') : ''}
        </p>
        {!typing ? (
          <button type="button" onClick={() => setTyping(true)}
            className="w-full min-h-[52px] rounded-[18px] bg-white/10 text-base font-semibold ring-1 ring-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
            {t('scan.typeInstead')}
          </button>
        ) : (
          <form className="rounded-[22px] bg-white p-3 text-[var(--ink)]" onSubmit={(e) => { e.preventDefault(); void submitCode(); }}>
            <label htmlFor="scan-code" className="mb-1 block text-sm font-semibold">{t('scan.codeLabel')}</label>
            <div className="flex gap-2">
              <input id="scan-code" autoFocus value={code} onChange={(e) => { setCode(e.target.value); setCodeError(null); }}
                placeholder="HP-07" autoCapitalize="characters" autoComplete="off" inputMode="text" maxLength={16}
                className="min-h-[48px] min-w-0 flex-1 rounded-xl border border-[var(--line)] px-3 text-lg uppercase placeholder:normal-case focus:border-[var(--green)] focus:outline-none" style={{ fontFamily: 'var(--font-heading)' }} />
              <button type="submit" disabled={!code.trim()}
                className="min-h-[48px] rounded-xl bg-[var(--green)] px-5 font-semibold text-white disabled:opacity-50">{t('scan.open')}</button>
            </div>
            {codeError && <p role="alert" className="mt-2 text-sm text-[var(--alert)]">{codeError}</p>}
          </form>
        )}
      </div>
    </div>
  );
}
