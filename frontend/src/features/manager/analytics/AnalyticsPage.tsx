/**
 * W3 Analytics (/manager/analytics). Any supervisor.
 * Is Kaarigar helping? Questions and answers, whether fixes worked, how fast experts reply, which machines
 * cause the most questions, what Kaarigar couldn't answer, and who on the team adds the knowledge
 * (the old separate "Team" screen lives here now).
 */
import { useQuery } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { getAnalytics, type Analytics, type Days } from '../manageApi';
import { Banner, Btn, Card, Chip, dateFmt, Empty, heading, Page, Segmented, Spinner } from '../ui/kit';
import { Legend, MachinesBars, QuestionsPerDay } from './charts';

const pct = (n: number | null | undefined) => (n == null ? '–' : `${Math.round(n * 100)}%`);

function Tile({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-sm font-semibold text-[var(--ink-muted)]">{label}</div>
      <div className="mt-1 text-[34px] font-semibold leading-none" style={heading}>{value}</div>
      {note && <div className="mt-1.5 text-sm text-[var(--ink-muted)]">{note}</div>}
    </Card>
  );
}

function minutes(t: TFunction, m: number | null) {
  if (m == null) return '–';
  return m < 90 ? t('manage.analytics.min', { count: Math.round(m) }) : t('manage.analytics.hours', { count: Math.round(m / 6) / 10 });
}

function Tiles({ a }: { a: Analytics }) {
  const { t } = useTranslation();
  const q = a.questions, fb = a.feedback;
  return (
    <div className="grid grid-cols-4 gap-4">
      <Tile label={t('manage.analytics.tile.questions')} value={q.total.toLocaleString()}
        note={q.total ? t('manage.analytics.tile.questionsNote', { voice: Math.round((q.voice / q.total) * 100) }) : undefined} />
      <Tile label={t('manage.analytics.tile.answered')} value={pct(q.answered_rate)}
        note={q.first_word_ms != null ? t('manage.analytics.tile.answeredNote', { s: (q.first_word_ms / 1000).toFixed(1) }) : undefined} />
      <Tile label={t('manage.analytics.tile.fixed')} value={fb.total ? pct(fb.fixed / fb.total) : '–'}
        note={fb.total ? t('manage.analytics.tile.fixedNote', { fixed: fb.fixed, total: fb.total }) : t('manage.analytics.tile.noFeedback')} />
      <Tile label={t('manage.analytics.tile.escalations')} value={a.escalations.created}
        note={t('manage.analytics.tile.escalationsNote', { open: a.escalations.open_now, time: minutes(t, a.escalations.minutes_to_answer) })} />
    </div>
  );
}

function PerDayCard({ a }: { a: Analytics }) {
  const { t, i18n } = useTranslation();
  const [table, setTable] = useState(false);
  return (
    <Card className="p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold" style={heading}>{t('manage.analytics.perDay.title')}</h2>
        <div className="flex items-center gap-4">
          <Legend />
          <Btn small kind="ghost" aria-pressed={table} onClick={() => setTable((v) => !v)}>{table ? t('manage.analytics.showChart') : t('manage.analytics.showTable')}</Btn>
        </div>
      </div>
      {table ? (
        <div className="max-h-[220px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[var(--white)] text-xs text-[var(--ink-muted)]">
              <tr><th scope="col" className="py-1 text-left font-semibold">{t('manage.analytics.perDay.day')}</th><th scope="col" className="py-1 text-right font-semibold">{t('manage.analytics.perDay.questions')}</th><th scope="col" className="py-1 text-right font-semibold">{t('manage.analytics.perDay.answered')}</th><th scope="col" className="py-1 text-right font-semibold">{t('manage.analytics.perDay.escalated')}</th></tr>
            </thead>
            <tbody className="tabular-nums">
              {[...a.per_day].reverse().map((d) => (
                <tr key={d.day} className="border-t border-[var(--line)]"><td className="py-1">{dateFmt(d.day, i18n.language)}</td><td className="py-1 text-right">{d.questions}</td><td className="py-1 text-right">{d.answered}</td><td className="py-1 text-right">{d.escalated}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <QuestionsPerDay data={a.per_day} lang={i18n.language} />}
    </Card>
  );
}

export default function AnalyticsPage() {
  const { t, i18n } = useTranslation();
  const [days, setDays] = useState<Days>(30);
  const q = useQuery({ queryKey: ['manage', 'analytics', days], queryFn: () => getAnalytics(days), placeholderData: (p) => p });
  const a = q.data;

  return (
    <Page title={t('manage.analytics.title')} subtitle={t('manage.analytics.subtitle')}
      actions={<Segmented label={t('manage.analytics.range')} value={days} onChange={setDays} options={[
        { value: 7, label: t('manage.analytics.days', { count: 7 }) },
        { value: 30, label: t('manage.analytics.days', { count: 30 }) },
        { value: 90, label: t('manage.analytics.days', { count: 90 }) },
      ]} />}>
      {q.isLoading ? <Spinner size={24} /> : q.isError || !a ? <Banner tone="alert">{t('manage.errors.load')}</Banner> : (
        <div className={`h-full space-y-5 overflow-y-auto pb-6 transition-opacity ${q.isFetching ? 'opacity-60' : ''}`}>
          {a.questions.total === 0 && <Banner>{t('manage.analytics.noQuestions')}</Banner>}
          <Tiles a={a} />
          <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-5">
            <PerDayCard a={a} />
            <Card className="p-5">
              <h2 className="mb-1 text-lg font-semibold" style={heading}>{t('manage.analytics.machines.title')}</h2>
              <p className="mb-3 text-sm text-[var(--ink-muted)]">{t('manage.analytics.machines.subtitle')}</p>
              {a.machines.length ? <MachinesBars data={a.machines} /> : <p className="text-sm text-[var(--ink-muted)]">{t('manage.analytics.none')}</p>}
            </Card>
          </div>

          <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-5">
            <Card className="p-5">
              <div className="mb-3 flex items-baseline justify-between gap-3">
                <h2 className="text-lg font-semibold" style={heading}>{t('manage.analytics.gaps.title')}</h2>
                <Link to="/manager/escalations" className="text-sm font-semibold text-[var(--green-deep)] hover:underline">{t('manage.analytics.gaps.open')}</Link>
              </div>
              {!a.gaps.length ? <p className="text-sm text-[var(--ink-muted)]">{t('manage.analytics.gaps.none')}</p> : (
                <ul className="divide-y divide-[var(--line)]">
                  {a.gaps.map((g) => (
                    <li key={g.id} className="flex items-start gap-3 py-2.5">
                      {g.machine && <b className="w-[64px] shrink-0 text-[var(--green-deep)]" style={heading}>{g.machine}</b>}
                      <div className="min-w-0 flex-1">
                        <div className="leading-snug">{g.question ?? '–'}</div>
                        <div className="text-xs text-[var(--ink-muted)]">{dateFmt(g.created_at, i18n.language, false)}</div>
                      </div>
                      {g.status === 'no_answer' ? <Chip tone="history">{t('manage.analytics.gaps.noAnswer')}</Chip> : g.status === 'failed' ? <Chip tone="alert">{t('manage.analytics.gaps.failed')}</Chip> : null}
                      {g.escalation_status && <Chip tone={g.escalation_status === 'open' ? 'safety' : 'green'}>{t(`manage.analytics.gaps.esc.${g.escalation_status}`)}</Chip>}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold" style={heading}>{t('manage.analytics.notes.title')}</h2>
              <dl className="space-y-3">
                {([
                  ['sent', a.notes.sent], ['approved', a.notes.approved], ['rejected', a.notes.rejected], ['pending', a.notes.pending_now],
                ] as const).map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-2 border-b border-[var(--line)] pb-2 last:border-0">
                    <dt className="text-sm">{t(`manage.analytics.notes.${k}`)}</dt><dd className="font-semibold tabular-nums">{v}</dd>
                  </div>
                ))}
                <div className="flex items-baseline justify-between gap-2">
                  <dt className="text-sm">{t('manage.analytics.notes.review')}</dt>
                  <dd className="font-semibold">{a.notes.hours_to_review == null ? '–' : t('manage.analytics.hours', { count: a.notes.hours_to_review })}</dd>
                </div>
              </dl>
              {a.notes.pending_now > 0 && <Link to="/manager" className="mt-3 inline-block text-sm font-semibold text-[var(--green-deep)] hover:underline">{t('manage.analytics.notes.goReview')}</Link>}
            </Card>
          </div>

          <Card className="p-5">
            <h2 className="mb-1 text-lg font-semibold" style={heading}>{t('manage.analytics.team.title')}</h2>
            <p className="mb-3 text-sm text-[var(--ink-muted)]">{t('manage.analytics.team.subtitle')}</p>
            {!a.team.length ? <Empty title={t('manage.analytics.none')} /> : (
              <table className="w-full text-left text-[15px]">
                <thead className="border-b border-[var(--line)] text-xs text-[var(--ink-muted)]">
                  <tr>
                    <th scope="col" className="py-2 font-semibold">{t('manage.analytics.team.person')}</th>
                    <th scope="col" className="py-2 text-right font-semibold">{t('manage.analytics.team.questions')}</th>
                    <th scope="col" className="py-2 text-right font-semibold">{t('manage.analytics.team.notes')}</th>
                    <th scope="col" className="py-2 text-right font-semibold">{t('manage.analytics.team.replies')}</th>
                    <th scope="col" className="py-2 text-right font-semibold">{t('manage.analytics.team.used')}</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {a.team.map((p) => (
                    <tr key={p.id} className="border-b border-[var(--line)] last:border-0">
                      <td className="py-2"><span className="font-semibold">{p.name}</span> <span className="text-sm text-[var(--ink-muted)]">· {t(`manage.role.${p.role}`)}</span></td>
                      <td className="py-2 text-right">{p.questions || '–'}</td>
                      <td className="py-2 text-right">{p.notes_sent ? `${p.notes_approved} / ${p.notes_sent}` : '–'}</td>
                      <td className="py-2 text-right">{p.answers_given || '–'}</td>
                      <td className="py-2 text-right font-semibold">{p.knowledge_used || '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </Page>
  );
}
