/**
 * Printable QR stickers (/manager/setup/machines/stickers?ids=a,b,c). A4, 2 × 4 stickers of 90 × 64 mm.
 * The QR opens PUBLIC_APP_URL/m/<token> → the machine screen on the technician's phone.
 * After printing, "Mark as printed" records the date so the Machines list shows which machines still need one.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage, getStickers, markPrinted, type Sticker } from '../manageApi';
import { Banner, Btn, Page, Spinner } from '../ui/kit';

const PER_PAGE = 8;

function StickerCard({ s }: { s: Sticker }) {
  const { t } = useTranslation();
  const meta = [s.line, s.model].filter(Boolean).join(' · ');
  // Long codes step down a size so they never run into the divider.
  const codeSize = s.code.length > 7 ? '17pt' : s.code.length > 5 ? '20pt' : '23pt';

  return (
    <div
      className="sticker flex overflow-hidden rounded-[3mm] border-[0.4mm] border-[var(--ink)] bg-white"
      style={{ width: '90mm', height: '64mm' }}
    >
      {/* QR panel: 42 mm QR, 3 mm breathing room. SVG comes from the backend (segno). */}
      <div className="flex shrink-0 items-center justify-center p-[3mm]" style={{ width: '48mm' }}>
        <div
          style={{ width: '42mm', height: '42mm' }}
          dangerouslySetInnerHTML={{ __html: s.svg.replace('<svg ', '<svg width="100%" height="100%" ') }}
        />
      </div>

      <div className="my-[3mm] w-[0.3mm] shrink-0 bg-[var(--line)]" />

      <div className="flex min-w-0 flex-1 flex-col px-[3.5mm] py-[3.5mm]">
        {/* Brand mark */}
        <div className="flex items-center gap-[1.2mm]">
          <span className="h-[1.6mm] w-[1.6mm] shrink-0 rounded-full bg-[var(--green-deep)]" />
          <span
            className="font-semibold uppercase leading-none text-[var(--green-deep)]"
            style={{ fontSize: '5.5pt', letterSpacing: '0.16em' }}
          >
            Kaarigar AI
          </span>
        </div>

        {/* Machine code is the thing people look for across the shop floor */}
        <div
          className="mt-[2mm] font-head font-bold leading-none tracking-tight text-[var(--ink)]"
          style={{ fontSize: codeSize }}
        >
          {s.code}
        </div>
        {s.name && (
          <div
            className="mt-[1.5mm] font-semibold leading-[1.2] text-[var(--ink)]"
            style={{
              fontSize: '8.5pt',
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {s.name}
          </div>
        )}
        {meta && (
          <div className="mt-[1mm] truncate leading-tight text-[var(--ink-muted)]" style={{ fontSize: '7pt' }}>
            {meta}
          </div>
        )}

        <div className="mt-auto flex items-center gap-[1.2mm] border-t border-[var(--line)] pt-[2mm]">
          <svg
            width="9"
            height="9"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 text-[var(--green-deep)]"
            aria-hidden
          >
            <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3" />
            <path d="M8 12h8" />
          </svg>
          <span className="font-semibold leading-tight text-[var(--green-deep)]" style={{ fontSize: '7.5pt' }}>
            {t('manage.stickers.scan')}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function StickerSheet() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const ids = (params.get('ids') ?? '').split(',').filter(Boolean);
  const [done, setDone] = useState(false);
  const q = useQuery({ queryKey: ['manage', 'stickers', ids.join(',')], queryFn: () => getStickers(ids), enabled: ids.length > 0, staleTime: Infinity });
  const mark = useMutation({
    mutationFn: () => markPrinted(ids),
    onSuccess: () => { setDone(true); qc.invalidateQueries({ queryKey: ['manage', 'machines'] }); },
  });
  const items = q.data?.items ?? [];
  const pages: Sticker[][] = [];
  for (let i = 0; i < items.length; i += PER_PAGE) pages.push(items.slice(i, i + PER_PAGE));

  return (
    <Page title={t('manage.stickers.title', { count: ids.length })} subtitle={t('manage.stickers.subtitle')}
      actions={<>
        <Btn onClick={() => nav('/manager/setup/machines')}>{t('manage.stickers.back')}</Btn>
        <Btn kind="primary" disabled={!items.length} onClick={() => window.print()}>{t('manage.stickers.print')}</Btn>
      </>}>
      {!ids.length ? <Banner>{t('manage.stickers.none')}</Banner>
        : q.isLoading ? <Spinner size={24} />
        : q.isError ? <Banner tone="alert">{errorMessage(q.error) ?? t('manage.errors.load')}</Banner>
        : (
          <div className="space-y-4">
            <Banner tone={done ? 'ok' : 'info'} action={!done && <Btn small kind="primary" busy={mark.isPending} onClick={() => mark.mutate()}>{t('manage.stickers.markPrinted')}</Btn>}>
              {done ? t('manage.stickers.marked', { count: items.length }) : t('manage.stickers.tip')}
            </Banner>
            {mark.isError && <Banner tone="alert">{errorMessage(mark.error) ?? t('manage.errors.generic')}</Banner>}
            <div id="sticker-sheet" className="space-y-6">
              {pages.map((pg, i) => (
                <div key={i} className="sheet mx-auto grid grid-cols-2 content-start justify-center gap-[6mm] border border-line/70 bg-white p-[10mm] shadow-[0_2px_14px_rgba(28,38,38,0.10)]" style={{ width: '210mm', minHeight: '297mm' }}>
                  {Array.from({ length: PER_PAGE }).map((_, slot) =>
                    pg[slot]
                      ? <StickerCard key={pg[slot]!.id} s={pg[slot]!} />
                      : <div key={`slot-${slot}`} className="sticker-slot" aria-hidden style={{ width: '90mm', height: '64mm' }} />,
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      <style>{`
        .sticker-slot {
          border: 0.4mm dashed var(--line);
          border-radius: 3mm;
          background: rgba(28, 38, 38, 0.02);
        }
        .sticker svg { display: block; shape-rendering: crispEdges; }
        @page { size: A4; margin: 0; }
        @media print {
          body * { visibility: hidden !important; }
          #sticker-sheet, #sticker-sheet * { visibility: visible !important; }
          #sticker-sheet { position: absolute; left: 0; top: 0; }
          #sticker-sheet .sheet { border: 0 !important; box-shadow: none !important; margin: 0 !important; }
          #sticker-sheet .sheet:not(:last-child) { break-after: page; }
          #sticker-sheet .sticker-slot { display: none !important; }
          #sticker-sheet { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        }`}</style>
    </Page>
  );
}
