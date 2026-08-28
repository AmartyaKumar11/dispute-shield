import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Loader2, Minus, RefreshCw } from 'lucide-react'
import { getDispute, retryDispute } from '../lib/api'
import { evidenceChecklist, formatDate, formatRupees, TERMINAL } from '../lib/format'
import EvidenceTimeline from './EvidenceTimeline'
import StatusBadge from './StatusBadge'

function prettyField(name) {
  return name.replaceAll('_', ' ')
}

export default function DisputeDetail({ disputeId, onRetried }) {
  const [dispute, setDispute] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [retrying, setRetrying] = useState(false)

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

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Dispute detail</p>
          <h2 className="mt-1 font-mono text-[18px] font-semibold tracking-[-0.02em]">{dispute.id}</h2>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusBadge status={dispute.status} />
            <span className="rounded-pill border border-white/[0.08] px-2.5 py-1 text-[12px] text-muted">
              {strategy.display_name || dispute.reason_code}
            </span>
            {polling ? (
              <span className="text-[11px] text-info animate-pulseSoft">Processing…</span>
            ) : null}
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-[22px] font-bold">{formatRupees(dispute.amount_rupees)}</div>
          <div className="mt-1 text-[12px] text-muted">Respond by {formatDate(dispute.respond_by)}</div>
        </div>
      </div>

      <section>
        <p className="eyebrow mb-3">Evidence timeline</p>
        <div className="elevated-card px-4 py-5">
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

      <section>
        <p className="eyebrow mb-3">Evidence collected</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {checklist.length === 0 ? (
            <p className="text-sm text-muted">Strategy not assigned yet.</p>
          ) : (
            checklist.map((item) => (
              <div key={item.name} className="elevated-card flex items-center justify-between px-4 py-3">
                <span className="text-[13px] capitalize text-ink">{prettyField(item.name)}</span>
                <EvidenceState state={item.state} />
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <p className="eyebrow mb-3">Generated explanation letter</p>
        <div className="surface-card max-h-[320px] overflow-y-auto px-5 py-4">
          {dispute.explanation_letter ? (
            <pre className="whitespace-pre-wrap font-sans text-[14px] font-normal leading-[1.7] text-ink">
              {dispute.explanation_letter}
            </pre>
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
      <span className="inline-flex items-center gap-1.5 text-[12px] text-[#FBBF24]">
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
