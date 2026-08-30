import { useEffect, useState } from 'react'
import { Mail } from 'lucide-react'
import { generatePortalLink, getRiskSummary, getRisks } from '../lib/api'
import { formatDate, formatRupees, truncateId } from '../lib/format'

function scoreColor(score) {
  if (score > 50) return 'text-[#F87171]'
  if (score >= 25) return 'text-[#FBBF24]'
  return 'text-[#4ADE80]'
}

export default function ShieldPanel({ refreshKey, onOpenDispute }) {
  const [risks, setRisks] = useState([])
  const [summary, setSummary] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        setLoading(true)
        const [list, sum] = await Promise.all([getRisks(), getRiskSummary()])
        if (!alive) return
        setRisks(list.risks || [])
        setSummary(sum)
        setError(null)
      } catch (err) {
        if (alive) setError(err.message || 'Failed to load shield data')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [refreshKey])

  const protectedCount = summary?.transactions_protected ?? risks.length
  const fieldsPre = summary?.evidence_fields_precollected ?? 0
  const anticipated = summary?.disputes_anticipated ?? 0
  const hitRate = summary?.vault_hit_rate != null ? `${(summary.vault_hit_rate * 100).toFixed(0)}%` : '—'

  return (
    <div className="space-y-6">
      <div className="elevated-card border-l-2 border-l-accent px-6 py-6">
        <p className="eyebrow">Shield status</p>
        <p className="mt-2 font-mono text-[36px] font-bold tracking-tight text-ink">
          {protectedCount} transactions protected
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Pill>{fieldsPre} evidence fields pre-collected</Pill>
          <Pill>{anticipated} disputes anticipated</Pill>
          <Pill>{hitRate} vault hit rate</Pill>
        </div>
      </div>

      <div className="surface-card overflow-hidden">
        <div className="border-b border-white/[0.06] px-5 py-4">
          <p className="eyebrow">Evidence vault</p>
          <h2 className="mt-1 text-[15px] font-medium">Protected transactions</h2>
        </div>
        {loading ? (
          <p className="p-6 text-sm text-muted">Loading…</p>
        ) : error ? (
          <p className="p-6 text-sm text-[#F87171]">{error}</p>
        ) : (
          <div className="max-h-[min(680px,72vh)] overflow-y-auto">
            {risks.map((r) => {
              const open = expanded === r.payment_id
              const method = (r.payment_method || 'card').toLowerCase()
              const filled = r.vault_field_count || 0
              const total = r.vault_field_total || 5
              const disputed = r.alert_status === 'dispute_filed' || r.dispute_id
              const statusLabel = disputed ? 'Disputed' : r.risk_score >= 50 ? 'Protected' : 'Clean'
              const statusClass = disputed
                ? 'border-danger/40 bg-danger/15 text-[#F87171]'
                : r.risk_score >= 50
                  ? 'border-accent/30 bg-accent/10 text-accent'
                  : 'border-white/10 bg-white/5 text-muted'
              return (
                <div key={r.payment_id} className="border-b border-white/[0.06]">
                  <button
                    type="button"
                    onClick={() => setExpanded(open ? null : r.payment_id)}
                    className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-elevated"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[13px]">{truncateId(r.payment_id)}</span>
                        <span
                          className={`rounded-pill px-2 py-0.5 text-[10px] uppercase ${
                            method === 'upi'
                              ? 'bg-[#7C3AED]/20 text-[#C4B5FD]'
                              : 'bg-info/15 text-[#60A5FA]'
                          }`}
                        >
                          {method === 'upi' ? 'UPI' : 'Card'}
                        </span>
                        <span className={`rounded-pill border px-2 py-0.5 text-[11px] ${statusClass}`}>
                          {statusLabel}
                        </span>
                        {r.intervention_email_status === 'sent' ? (
                          <span
                            title={`Email sent to ${r.customer_email || 'customer'} at ${formatDate(r.intervention_sent_at)}`}
                            className="inline-flex items-center gap-1 rounded-pill border border-accent/30 bg-accent/10 px-2 py-0.5 text-[11px] text-accent"
                          >
                            <Mail size={11} /> Email sent ✓
                          </span>
                        ) : null}
                        {r.intervention_email_status === 'failed' ? (
                          <span className="rounded-pill border border-warn/40 bg-warn/10 px-2 py-0.5 text-[11px] text-[#FBBF24]">
                            Email failed ⚠
                          </span>
                        ) : null}
                        {r.intervention_email_status === 'dry_run' ? (
                          <span className="rounded-pill border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-muted">
                            Email dry-run
                          </span>
                        ) : null}
                        {r.portal_badge === 'resolved' ? (
                          <span className="rounded-pill border border-accent/30 bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
                            Resolved via portal ✓
                          </span>
                        ) : r.portal_badge === 'visited' ? (
                          <span className="rounded-pill border border-info/30 bg-info/10 px-2 py-0.5 text-[11px] text-[#60A5FA]">
                            Portal visited
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-2 flex items-center gap-3">
                        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-white/[0.08]">
                          <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${(filled / total) * 100}%` }}
                          />
                        </div>
                        <span className="font-mono text-[11px] text-muted">
                          {filled}/{total} fields
                        </span>
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="font-mono text-[13px]">{formatRupees(r.amount_rupees)}</div>
                      <div className={`mt-1 font-mono text-[12px] font-bold ${scoreColor(r.risk_score)}`}>
                        {Number(r.risk_score).toFixed(0)}
                      </div>
                    </div>
                  </button>
                  {open ? (
                    <div className="space-y-4 bg-page/50 px-5 pb-5">
                      <div>
                        <p className="text-[11px] uppercase tracking-[0.06em] text-label">Risk factors</p>
                        <ul className="mt-2 space-y-1 text-[13px]">
                          {(r.risk_factors || []).length ? (
                            r.risk_factors.map((f) => (
                              <li key={f.factor + f.signal} className="text-ink">
                                <span className="text-[#FBBF24]">+{f.weight}</span> {f.signal || f.factor}
                              </li>
                            ))
                          ) : (
                            <li className="text-muted">No elevated factors</li>
                          )}
                        </ul>
                      </div>
                      <div>
                        <p className="text-[11px] uppercase tracking-[0.06em] text-label">
                          Evidence collection timeline
                        </p>
                        <ul className="mt-3 space-y-2">
                          {(r.vault_timeline || []).map((step) => (
                            <li
                              key={step.day + step.text}
                              className={`flex gap-2 text-[13px] leading-relaxed ${
                                step.warn
                                  ? 'text-[#FBBF24]'
                                  : step.ok
                                    ? 'text-[#4ADE80]'
                                    : 'text-muted'
                              }`}
                            >
                              <span className="shrink-0 font-mono">
                                {step.warn ? '⚠' : step.ok ? '✓' : '○'}
                              </span>
                              <span>{step.text}{step.ok && !step.warn ? ' ✓' : ''}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                      {r.dispute_id ? (
                        <button
                          type="button"
                          onClick={() => onOpenDispute?.(r.dispute_id)}
                          className="text-[13px] text-accent underline-offset-2 hover:underline"
                        >
                          Open linked dispute {truncateId(r.dispute_id)}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            const link = await generatePortalLink({
                              order_id: r.order_id,
                              payment_id: r.payment_id,
                              customer_email: r.customer_email,
                            })
                            await navigator.clipboard.writeText(link.portal_url)
                          } catch {
                            /* ignore */
                          }
                        }}
                        className="text-[12px] text-muted underline-offset-2 hover:text-accent hover:underline"
                      >
                        Copy portal link
                      </button>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function Pill({ children }) {
  return (
    <span className="rounded-pill border border-white/[0.08] bg-page px-3 py-1.5 text-[12px] text-muted">
      {children}
    </span>
  )
}
