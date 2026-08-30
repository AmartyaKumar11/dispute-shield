import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Loader2, Mail, Minus, RefreshCw } from 'lucide-react'
import {
  getDispute,
  retryDispute,
  forceSubmitDispute,
  acceptDispute,
  sendResolutionOffer,
  getPortalSessionsForOrder,
} from '../lib/api'
import { evidenceChecklist, formatDate, formatRupees, TERMINAL } from '../lib/format'
import EvidenceTimeline from './EvidenceTimeline'
import AIReasoning from './AIReasoning'
import StatusBadge from './StatusBadge'

function prettyField(name) {
  return name.replaceAll('_', ' ')
}

export default function DisputeDetail({ disputeId, onRetried }) {
  const [dispute, setDispute] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [retrying, setRetrying] = useState(false)
  const [acting, setActing] = useState(false)
  const [portalSessions, setPortalSessions] = useState([])

  useEffect(() => {
    if (!disputeId) {
      setDispute(null)
      return undefined
    }
    let alive = true
    let timer = null

    const load = async (silent = false) => {
      try {
        if (!silent) setLoading(true)
        const data = await getDispute(disputeId)
        if (!alive) return
        setDispute(data)
        setError(null)
        if (data.order_id) {
          try {
            const portal = await getPortalSessionsForOrder(data.order_id)
            if (alive) setPortalSessions(portal.sessions || [])
          } catch {
            if (alive) setPortalSessions([])
          }
        }
        if (TERMINAL.has(data.status) && timer) {
          clearInterval(timer)
          timer = null
        }
      } catch (err) {
        if (alive) setError(err.message || 'Failed to load dispute')
      } finally {
        if (alive) setLoading(false)
      }
    }

    load(false)
    timer = setInterval(() => load(true), 3000)
    return () => {
      alive = false
      if (timer) clearInterval(timer)
    }
  }, [disputeId])

  if (!disputeId) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center p-10 text-center">
        <p className="text-sm text-muted">Select a dispute to inspect evidence assembly.</p>
      </div>
    )
  }

  if (loading && !dispute) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center gap-2 text-muted">
        <Loader2 className="animate-spin" size={16} />
        <span className="text-sm">Loading dispute…</span>
      </div>
    )
  }

  if (error && !dispute) {
    return <p className="p-6 text-sm text-[#F87171]">{error}</p>
  }

  if (!dispute) return null

  const strategy = dispute.evidence_strategy || {}
  const checklist = evidenceChecklist(dispute)
  const polling = !TERMINAL.has(dispute.status)
  const usedFallback = Boolean(strategy.letter_fallback)
  const win = dispute.win_probability
  const winTone =
    win == null
      ? 'border-white/20 text-muted bg-white/5'
      : win > 70
        ? 'border-accent/50 text-[#4ADE80] bg-accent/10'
        : win >= 40
          ? 'border-warn/50 text-[#FBBF24] bg-warn/10'
          : 'border-danger/40 text-[#F87171] bg-danger/10'

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow">Dispute detail</p>
          <h2 className="mt-1 break-all font-mono text-[16px] font-semibold tracking-[-0.02em] md:text-[18px]">
            {dispute.id}
          </h2>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusBadge status={dispute.status} triage={dispute.triage_action} />
            <span className="rounded-pill border border-white/[0.08] px-2.5 py-1 text-[12px] text-muted">
              {strategy.display_name || dispute.reason_code}
            </span>
            {dispute.triage_action ? (
              <span className="rounded-pill border border-white/[0.08] px-2.5 py-1 text-[11px] uppercase text-label">
                {dispute.triage_action.replaceAll('_', ' ')}
              </span>
            ) : null}
            {polling ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] text-info animate-pulseSoft">
                <Loader2 size={12} className="animate-spin" />
                Processing…
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex items-start gap-4 text-right">
          {win != null ? (
            <div
              className={`flex h-16 w-16 flex-col items-center justify-center rounded-full border-2 ${winTone}`}
            >
              <span className="font-mono text-[16px] font-bold">{Number(win).toFixed(0)}</span>
              <span className="text-[9px] uppercase text-muted">win%</span>
            </div>
          ) : null}
          <div>
            <div className="font-mono text-[22px] font-bold">{formatRupees(dispute.amount_rupees)}</div>
            <div className="mt-1 text-[12px] text-muted">Respond by {formatDate(dispute.respond_by)}</div>
          </div>
        </div>
      </div>

      {dispute.status === 'review' ? (
        <section className="elevated-card space-y-3 px-4 py-4">
          <p className="text-sm text-[#FBBF24]">Needs review — contest package ready, not submitted.</p>
          {dispute.review_reason ? (
            <p className="text-[13px] text-muted">{dispute.review_reason}</p>
          ) : null}
          {dispute.resolution_offer_status === 'sent' ? (
            <p
              title={`Email sent to ${dispute.resolution_offer_email || 'customer'} at ${formatDate(dispute.resolution_offer_sent_at)}`}
              className="inline-flex items-center gap-1.5 text-[13px] text-accent"
            >
              <Mail size={14} /> Resolution offer sent ✓ · {formatDate(dispute.resolution_offer_sent_at)}
            </p>
          ) : null}
          {dispute.resolution_offer_status === 'failed' ? (
            <p className="text-[13px] text-[#FBBF24]">Resolution offer email failed ⚠</p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={acting}
              onClick={async () => {
                try {
                  setActing(true)
                  await forceSubmitDispute(dispute.id)
                  onRetried?.(dispute.id)
                } catch (err) {
                  setError(err.message || 'Submit failed')
                } finally {
                  setActing(false)
                }
              }}
              className="rounded-pill bg-accent px-4 py-2 text-[13px] font-medium text-page hover:bg-accent-hover disabled:opacity-60"
            >
              Submit Contest
            </button>
            <button
              type="button"
              disabled={acting}
              onClick={async () => {
                try {
                  setActing(true)
                  await acceptDispute(dispute.id)
                  onRetried?.(dispute.id)
                } catch (err) {
                  setError(err.message || 'Accept failed')
                } finally {
                  setActing(false)
                }
              }}
              className="rounded-pill border border-white/15 px-4 py-2 text-[13px] text-ink hover:bg-elevated disabled:opacity-60"
            >
              Accept Dispute
            </button>
            <button
              type="button"
              disabled={acting}
              onClick={async () => {
                try {
                  setActing(true)
                  await sendResolutionOffer(dispute.id)
                  onRetried?.(dispute.id)
                } catch (err) {
                  setError(err.message || 'Resolution email failed')
                } finally {
                  setActing(false)
                }
              }}
              className="inline-flex items-center gap-1.5 rounded-pill border border-info/40 bg-info/10 px-4 py-2 text-[13px] text-[#60A5FA] hover:bg-info/20 disabled:opacity-60"
            >
              <Mail size={14} /> Send resolution offer
            </button>
          </div>
        </section>
      ) : null}

      {dispute.status === 'accepted' ? (
        <section className="elevated-card space-y-3 px-4 py-4">
          <p className="text-sm text-muted">Dispute accepted — contest skipped.</p>
          {dispute.review_reason ? (
            <p className="text-[13px] text-muted">{dispute.review_reason}</p>
          ) : null}
          {dispute.resolution_offer_status === 'sent' ? (
            <p
              title={`Email sent to ${dispute.resolution_offer_email || 'customer'} at ${formatDate(dispute.resolution_offer_sent_at)}`}
              className="inline-flex items-center gap-1.5 text-[13px] text-accent"
            >
              <Mail size={14} /> Resolution offer sent ✓ · {formatDate(dispute.resolution_offer_sent_at)}
            </p>
          ) : null}
          <button
            type="button"
            disabled={acting}
            onClick={async () => {
              try {
                setActing(true)
                await forceSubmitDispute(dispute.id)
                onRetried?.(dispute.id)
              } catch (err) {
                setError(err.message || 'Contest failed')
              } finally {
                setActing(false)
              }
            }}
            className="rounded-pill bg-accent px-4 py-2 text-[13px] font-medium text-page hover:bg-accent-hover disabled:opacity-60"
          >
            Contest Anyway
          </button>
        </section>
      ) : null}

      <section>
        <p className="eyebrow mb-3">Evidence timeline</p>
        <div className="elevated-card overflow-x-auto px-4 py-5">
          <EvidenceTimeline
            status={dispute.status}
            createdAt={formatDate(dispute.created_at)}
            completedAt={
              dispute.processing_time_seconds != null
                ? `${Number(dispute.processing_time_seconds).toFixed(1)}s`
                : null
            }
          />
        </div>
      </section>

      <AIReasoning dispute={dispute} />

      {portalSessions.length ? (
        <section className="space-y-3">
          <p className="eyebrow">Portal activity</p>
          <div className="elevated-card space-y-3 px-4 py-4">
            <p className="text-[13px] text-[#FBBF24]">
              Customer used portal before filing dispute
            </p>
            {portalSessions.map((s) => (
              <div key={s.id} className="border-t border-white/[0.06] pt-3 text-[13px]">
                <p className="text-muted">
                  Status {s.status} · viewed={String(s.viewed_order_status)} · refund=
                  {String(s.requested_refund)} · chat={String(s.started_chat)}
                </p>
                {(s.chat_history || []).length ? (
                  <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-[12px] text-ink">
                    {s.chat_history.map((m, i) => (
                      <li key={i}>
                        <span className="text-label">{m.role}:</span> {m.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section>
        <p className="eyebrow mb-3">Evidence collected</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {checklist.length === 0 ? (
            <p className="text-sm text-muted">Strategy not assigned yet.</p>
          ) : (
            checklist.map((item) => (
              <div key={item.name} className="elevated-card flex items-center justify-between gap-3 px-4 py-3">
                <span className="text-[13px] capitalize text-ink">{prettyField(item.name)}</span>
                <EvidenceState state={item.state} />
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <p className="eyebrow">Generated explanation letter</p>
          {usedFallback ? (
            <span className="rounded-pill border border-warn/40 bg-warn/15 px-2 py-0.5 text-[11px] text-[#FBBF24]">
              Fallback letter
            </span>
          ) : null}
        </div>
        <div className="surface-card max-h-[320px] overflow-y-auto px-5 py-4">
          {dispute.explanation_letter ? (
            <pre className="whitespace-pre-wrap font-sans text-[14px] font-normal leading-[1.7] text-ink">
              {dispute.explanation_letter}
            </pre>
          ) : dispute.status === 'accepted' ? (
            <p className="py-6 text-sm text-muted">Letter skipped — dispute accepted.</p>
          ) : (
            <div className="flex items-center gap-2 py-8 text-muted">
              <Loader2 className="animate-spin" size={16} />
              <span className="text-sm">Generating…</span>
            </div>
          )}
        </div>
      </section>

      {strategy.description ? (
        <section>
          <p className="eyebrow mb-2">Strategy used</p>
          <p className="text-[14px] leading-relaxed text-muted">{strategy.description}</p>
          {strategy.letter_focus ? (
            <p className="mt-2 text-[13px] leading-relaxed text-label">{strategy.letter_focus}</p>
          ) : null}
        </section>
      ) : null}

      {dispute.status === 'error' ? (
        <section className="rounded-card border border-danger/30 bg-danger/10 px-4 py-3">
          <p className="text-sm text-[#F87171]">{dispute.error_message || 'Pipeline failed.'}</p>
          <button
            type="button"
            disabled={retrying}
            onClick={async () => {
              try {
                setRetrying(true)
                await retryDispute(dispute.id)
                onRetried?.(dispute.id)
              } catch (err) {
                setError(err.message || 'Retry failed')
              } finally {
                setRetrying(false)
              }
            }}
            className="mt-3 inline-flex items-center gap-2 rounded-pill bg-accent px-4 py-2 text-[13px] font-medium text-page hover:bg-accent-hover disabled:opacity-60"
          >
            <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
            {retrying ? 'Retrying…' : 'Retry'}
          </button>
        </section>
      ) : null}
    </div>
  )
}

function EvidenceState({ state }) {
  if (state === 'collected') {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] text-[#4ADE80]">
        <Check size={14} /> Collected
      </span>
    )
  }
  if (state === 'gap') {
    return (
      <span
        title="Gap — submitted without this evidence"
        className="inline-flex cursor-help items-center gap-1.5 text-[12px] text-[#FBBF24]"
      >
        <AlertTriangle size={14} /> Gap
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
      <Minus size={14} /> N/A
    </span>
  )
}
