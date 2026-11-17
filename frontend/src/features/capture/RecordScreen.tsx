/** 06 Record (/tech/machines/:code/record) — the expert talks, listens back, sends. */
import { useMutation } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import AudioPlayer from './AudioPlayer';
import { createRecord, errorCode } from './captureApi';
import { useRecorder } from './useRecorder';
import VoiceGauge from './VoiceGauge';
import { BigButton, Card, MachineChip, Screen, Spinner, TopBar } from './ui';

const MAX_SEC = 180;
const MIN_SEC = 3;

export default function RecordScreen() {
  const { code = '' } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const rec = useRecorder(MAX_SEC);
  const [sendError, setSendError] = useState<string | null>(null);
  const [hint, setHint] = useState(false);
  const hintTimer = useRef<number | null>(null);

  useEffect(() => () => { if (hintTimer.current) window.clearTimeout(hintTimer.current); }, []);

  const audioUrl = useMemo(() => (rec.blob ? URL.createObjectURL(rec.blob) : null), [rec.blob]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);

  const send = useMutation({
    mutationFn: () => createRecord(code, rec.blob as Blob, rec.mimeType),
    onSuccess: ({ record_id }) => nav(`/tech/records/${record_id}`, { replace: true }),
    onError: (e) => setSendError(errorCode(e)),
  });

  const recording = rec.state === 'recording';
  const tooShort = rec.state === 'stopped' && rec.seconds < MIN_SEC;

  const onGauge = () => {
    setSendError(null);
    if (recording) {
      // A second tap right after the mic permission prompt should not stop the note.
      if (rec.seconds < 2) {
        setHint(true);
        if (hintTimer.current) window.clearTimeout(hintTimer.current);
        hintTimer.current = window.setTimeout(() => setHint(false), 2000);
        return;
      }
      rec.stop();
    } else {
      rec.start();
    }
  };

  return (
    <Screen>
      <TopBar onBack={() => nav(`/tech/machines/${encodeURIComponent(code)}`)} title={t('capture.record.title')}
        right={<MachineChip code={code} />} />

      <Card className="mb-6">
        <p className="mb-2 font-semibold">{t('capture.record.promptTitle')}</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-[var(--ink-muted)]">
          <li>{t('capture.record.prompt1')}</li>
          <li>{t('capture.record.prompt2')}</li>
          <li>{t('capture.record.prompt3')}</li>
          <li>{t('capture.record.prompt4')}</li>
        </ol>
      </Card>

      {rec.state !== 'stopped' && (
        <>
          <p className="mb-3 flex min-h-6 items-center justify-center gap-2 text-sm" aria-live="polite">
            {rec.state === 'requesting' ? (
              <span className="inline-flex items-center gap-2 text-[var(--ink-muted)]">
                <Spinner size={16} /> {t('capture.record.micStarting')}
              </span>
            ) : recording ? (
              <span className="inline-flex items-center gap-2 font-semibold text-[var(--alert)]">
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--alert)] motion-safe:animate-pulse" />
                {t('capture.record.recordingNow')}
              </span>
            ) : (
              <span className="text-[var(--ink-muted)]">{t('capture.record.tapToStart')}</span>
            )}
          </p>
          <VoiceGauge recording={recording} level={rec.level} seconds={rec.seconds} maxSec={MAX_SEC}
            disabled={rec.state === 'requesting' || send.isPending} onPress={onGauge}
            label={recording ? t('capture.record.stop') : t('capture.record.start')} />
          <p className="mt-4 text-center text-sm text-[var(--ink-muted)]" aria-live="polite">
            {hint ? t('capture.record.keepTalking') : recording ? t('capture.record.tapToStop') : t('capture.record.tapToStart')}
          </p>
        </>
      )}

      {rec.state === 'error' && rec.error && (
        <p role="alert" className="mt-4 rounded-2xl bg-[var(--alert-tint)] px-4 py-3 text-sm text-[var(--alert)]">
          {t(`capture.record.errors.${rec.error}`)}
        </p>
      )}

      {rec.state === 'stopped' && audioUrl && (
        <div className="space-y-4">
          <AudioPlayer src={audioUrl} knownSeconds={rec.seconds} label={t('capture.record.listenBack')} />
          {tooShort && (
            <p role="alert" className="rounded-2xl bg-[var(--alert-tint)] px-4 py-3 text-sm text-[var(--alert)]">
              {t('capture.errors.too_short')}
            </p>
          )}
          {sendError && (
            <p role="alert" className="rounded-2xl bg-[var(--alert-tint)] px-4 py-3 text-sm text-[var(--alert)]">
              {t(`capture.errors.${sendError}`, { defaultValue: t('capture.errors.upload_failed') })}
            </p>
          )}
        </div>
      )}

      <div className="mt-auto space-y-3 pt-6">
        {rec.state === 'stopped' && (
          <>
            <BigButton onClick={() => send.mutate()} disabled={tooShort || send.isPending}>
              {send.isPending ? <span className="inline-flex items-center gap-2"><Spinner /> {t('capture.record.sending')}</span>
                : t('capture.record.send')}
            </BigButton>
            <BigButton kind="secondary" onClick={() => { setSendError(null); rec.reset(); }} disabled={send.isPending}>
              {t('capture.record.again')}
            </BigButton>
          </>
        )}
      </div>
    </Screen>
  );
}
