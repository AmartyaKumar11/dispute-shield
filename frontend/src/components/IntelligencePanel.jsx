import { useEffect, useState } from 'react'
import { getIntelligence } from '../lib/api'
import { formatRupees } from '../lib/format'

const PRIORITY = {
  high: 'border-danger/40 bg-danger/10 text-[#F87171]',
  medium: 'border-warn/40 bg-warn/10 text-[#FBBF24]',
  low: 'border-white/10 bg-white/5 text-muted',
}

export default function IntelligencePanel({ refreshKey }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        setLoading(true)
        const insights = await getIntelligence()
        if (!alive) return
        setData(insights)
        setError(null)
      } catch (err) {
        if (alive) setError(err.message || 'Failed to load insights')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [refreshKey])

  if (loading) return <p className="text-sm text-muted">Generating merchant insights…</p>
  if (error) return <p className="text-sm text-[#F87171]">{error}</p>
  if (!data) return null

  const reasons = data.top_reason_codes || []
  const maxCount = Math.max(...reasons.map((r) => r.count), 1)

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Disputes" value={data.total_disputes} />
        <Stat label="Amount at risk" value={formatRupees(data.total_amount_at_risk)} />
        <Stat label="Preventable" value={data.estimated_preventable_disputes} />
        <Stat label="Est. savings" value={formatRupees(data.estimated_savings_if_prevented)} />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
        Trend:{' '}
        <span className="rounded-pill border border-white/[0.08] px-2.5 py-1 capitalize text-ink">
          {data.dispute_rate_trend}
        </span>
        {data.used_fallback ? (
          <span className="rounded-pill border border-warn/40 bg-warn/15 px-2 py-0.5 text-[11px] text-[#FBBF24]">
            Rule-based insights
          </span>
        ) : (
          <span className="rounded-pill border border-accent/30 bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
            LLM insights
          </span>
        )}
      </div>

      <section>
        <p className="eyebrow mb-3">Reason code breakdown</p>
        <div className="space-y-3">
          {reasons.map((r) => (
            <div key={r.reason_code} className="elevated-card px-4 py-3">
              <div className="mb-2 flex items-center justify-between gap-3 text-[13px]">
                <span className="text-ink">{r.display_name}</span>
                <span className="font-mono text-muted">
                  {r.count} · {r.percentage.toFixed(0)}% · win {r.win_rate}%
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${(r.count / maxCount) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <p className="eyebrow mb-3">Risk hotspots</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {(data.risk_hotspots || []).map((h) => (
            <div key={`${h.dimension}-${h.value}`} className="elevated-card px-4 py-4">
              <p className="text-[11px] uppercase tracking-[0.06em] text-muted">{h.dimension}</p>
              <p className="mt-1 text-[15px] font-medium text-ink">{h.value}</p>
              <p className="mt-2 font-mono text-[13px] text-[#FBBF24]">{h.comparison}</p>
              <p className="mt-1 text-[12px] text-muted">
                {h.dispute_count} disputes · {h.dispute_rate}% rate
              </p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <p className="eyebrow mb-3">Prevention recommendations</p>
        <div className="space-y-3">
          {(data.prevention_recommendations || []).map((rec) => (
            <div key={rec.title} className="elevated-card px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-pill border px-2 py-0.5 text-[11px] uppercase ${PRIORITY[rec.priority] || PRIORITY.medium}`}
                >
                  {rec.priority}
                </span>
                <span className="rounded-pill border border-white/[0.08] px-2 py-0.5 text-[11px] text-muted">
                  {rec.action_type}
                </span>
              </div>
              <h3 className="mt-2 text-[15px] font-medium text-ink">{rec.title}</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{rec.description}</p>
              <p className="mt-2 text-[12px] text-accent">{rec.estimated_impact}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="elevated-card px-4 py-4">
      <p className="text-[11px] uppercase tracking-[0.06em] text-muted">{label}</p>
      <p className="mt-2 font-mono text-[20px] font-bold text-ink">{value}</p>
    </div>
  )
}
