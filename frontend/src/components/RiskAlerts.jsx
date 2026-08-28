import { useEffect, useState } from 'react'
import { getRiskSummary, getRisks } from '../lib/api'
import { formatDate, formatRupees, truncateId } from '../lib/format'

function scoreTone(score) {
  if (score >= 75) return 'text-[#F87171] bg-danger/15 border-danger/30'
  if (score >= 50) return 'text-[#FBBF24] bg-warn/15 border-warn/30'
  if (score >= 25) return 'text-[#60A5FA] bg-info/15 border-info/30'
  return 'text-[#4ADE80] bg-accent/15 border-accent/30'
}

export default function RiskAlerts({ refreshKey, onOpenDispute }) {
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
        if (alive) setError(err.message || 'Failed to load risks')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [refreshKey])

  const cards = [
    { label: 'Total transactions', value: summary?.total_transactions ?? '—' },
    { label: 'High risk', value: summary?.high_risk_count ?? '—' },
    { label: 'Alerts → disputes', value: summary?.alerts_that_became_disputes ?? '—' },
    {
      label: 'Flag accuracy',
      value:
        summary?.prediction_accuracy != null
          ? `${(summary.prediction_accuracy * 100).toFixed(0)}%`
          : '—',
    },
  ]

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cards.map((c) => (
          <div key={c.label} className="elevated-card px-4 py-4">
            <p className="text-[11px] uppercase tracking-[0.06em] text-muted">{c.label}</p>
            <p className="mt-2 font-mono text-[22px] font-bold text-ink">{c.value}</p>
          </div>
        ))}
      </div>

      <div className="surface-card overflow-hidden">
        <div className="border-b border-white/[0.06] px-5 py-4">
          <p className="eyebrow">Pre-dispute monitoring</p>
          <h2 className="mt-1 text-[15px] font-medium">Risk alerts</h2>
        </div>
        {loading ? (
          <p className="p-6 text-sm text-muted">Loading risks…</p>
        ) : error ? (
          <p className="p-6 text-sm text-[#F87171]">{error}</p>
        ) : (
          <div className="max-h-[min(640px,70vh)] overflow-y-auto">
            {risks.map((r) => {
              const open = expanded === r.payment_id
              return (
                <div key={r.payment_id} className="border-b border-white/[0.06]">
                  <button
                    type="button"
                    onClick={() => setExpanded(open ? null : r.payment_id)}
                    className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-elevated"
                  >
                    <span
                      className={`rounded-pill border px-2.5 py-1 font-mono text-[12px] font-bold ${scoreTone(r.risk_score)}`}
                    >
                      {Number(r.risk_score).toFixed(0)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[13px]">{truncateId(r.payment_id)}</span>
                        <span className="rounded-pill border border-white/[0.08] px-2 py-0.5 text-[11px] uppercase text-muted">
                          {r.risk_level}
                        </span>
                        {r.alert_status === 'dispute_filed' ? (
                          <span className="rounded-pill border border-danger/40 bg-danger/15 px-2 py-0.5 text-[11px] text-[#F87171]">
                            Dispute filed
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-[12px] text-muted">
                        Predicted: {(r.predicted_dispute_type || '—').replaceAll('_', ' ')}
                      </p>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[13px]">{formatRupees(r.amount_rupees)}</div>
                      <div className="mt-1 text-[11px] text-muted">{formatDate(r.created_at)}</div>
                    </div>
                  </button>
                  {open ? (
                    <div className="space-y-3 bg-page/40 px-5 pb-4">
                      <div>
                        <p className="text-[11px] uppercase tracking-[0.06em] text-label">Risk factors</p>
                        <ul className="mt-2 space-y-1 text-[13px]">
                          {(r.risk_factors || []).map((f) => (
                            <li key={f.factor + f.signal} className="text-ink">
                              <span className="text-[#FBBF24]">+{f.weight}</span> {f.signal || f.factor}
                            </li>
                          ))}
                          {!r.risk_factors?.length ? (
                            <li className="text-muted">No elevated factors</li>
                          ) : null}
                        </ul>
                      </div>
                      <div>
                        <p className="text-[11px] uppercase tracking-[0.06em] text-label">
                          Recommended actions
                        </p>
                        <ul className="mt-2 space-y-1 text-[13px] text-[#60A5FA]">
                          {(r.recommended_actions || []).map((a) => (
                            <li key={a}>→ {a}</li>
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
