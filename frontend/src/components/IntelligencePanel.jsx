import { useEffect, useState } from 'react'
import { getEvaluation, getIntelligence, getModelsInfo } from '../lib/api'
import { formatRupees } from '../lib/format'

const PRIORITY = {
  high: 'border-danger/40 bg-danger/10 text-[#F87171]',
  medium: 'border-warn/40 bg-warn/10 text-[#FBBF24]',
  low: 'border-white/10 bg-white/5 text-muted',
}

function metricTone(v) {
  if (v > 0.8) return 'text-[#4ADE80]'
  if (v >= 0.5) return 'text-[#FBBF24]'
  return 'text-[#F87171]'
}

export default function IntelligencePanel({ refreshKey }) {
  const [data, setData] = useState(null)
  const [evalReport, setEvalReport] = useState(null)
  const [modelsInfo, setModelsInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        setLoading(true)
        const [insights, evaluation, models] = await Promise.all([
          getIntelligence(),
          getEvaluation(),
          getModelsInfo(),
        ])
        if (!alive) return
        setData(insights)
        setEvalReport(evaluation)
        setModelsInfo(models)
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
  const rs = evalReport?.risk_scorer
  const triage = evalReport?.triage
  const vault = evalReport?.vault
  const cost = evalReport?.cost
  const triageTotal = Math.max(
    (triage?.auto_submitted || 0) + (triage?.sent_to_review || 0) + (triage?.recommended_accept || 0),
    1,
  )
  const winWith = Math.min(95, Math.round((vault?.avg_coverage_with_vault || 0) * 100 * 0.9))
  const winWithout = 8

  return (
    <div className="space-y-8">
      {rs ? (
        <section className="space-y-5">
          <div>
            <p className="eyebrow">AI performance metrics</p>
            <h2 className="mt-1 text-[18px] font-medium">Model evaluation</h2>
          </div>

          <div>
            <p className="mb-2 text-[12px] text-muted">Actual ↓ · Predicted →</p>
            <div className="grid grid-cols-2 gap-3 max-w-lg">
              <MatrixCell tone="green" label="True negatives" value={rs.true_negatives} />
              <MatrixCell tone="amber" label="False positives" value={rs.false_positives} />
              <MatrixCell tone="red" label="False negatives" value={rs.false_negatives} />
              <MatrixCell tone="green" label="True positives" value={rs.true_positives} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="Precision" value={rs.precision} />
            <MetricCard label="Recall" value={rs.recall} />
            <MetricCard label="F1 Score" value={rs.f1_score} />
          </div>
          <p className="text-[12px] text-muted">Production metrics (on live / seeded transactions)</p>

          {modelsInfo ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <TrainingCard
                title="Card model"
                status={modelsInfo.card_model?.status}
                dataset={modelsInfo.card_model?.dataset}
                metrics={modelsInfo.card_model?.metrics}
                threshold={modelsInfo.card_model?.threshold}
                topFeatures={modelsInfo.card_model?.top_features}
              />
              <TrainingCard
                title="UPI model"
                status={modelsInfo.upi_model?.status}
                dataset={modelsInfo.upi_model?.dataset}
                metrics={modelsInfo.upi_model?.metrics}
                threshold={modelsInfo.upi_model?.threshold}
                topFeatures={modelsInfo.upi_model?.top_features}
              />
            </div>
          ) : null}
          <p className="text-[12px] text-muted">Training metrics (on held-out test set)</p>

          {vault ? (
            <div className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
              <div className="elevated-card flex-1 border border-white/10 px-5 py-4">
                <p className="text-[12px] uppercase tracking-[0.06em] text-muted">Without vault</p>
                <p className="mt-3 text-[13px] text-ink">
                  Evidence coverage:{' '}
                  <span className="font-mono">{(vault.avg_coverage_without_vault * 100).toFixed(0)}%</span>
                </p>
                <p className="mt-1 text-[13px] text-muted">Estimated win rate: ~{winWithout}%</p>
              </div>
              <div className="shrink-0 text-center font-mono text-accent">
                → +{vault.improvement_pct}%
              </div>
              <div className="elevated-card flex-1 border border-accent/40 px-5 py-4">
                <p className="text-[12px] uppercase tracking-[0.06em] text-accent">With vault</p>
                <p className="mt-3 text-[13px] text-ink">
                  Evidence coverage:{' '}
                  <span className="font-mono">{(vault.avg_coverage_with_vault * 100).toFixed(0)}%</span>
                </p>
                <p className="mt-1 text-[13px] text-[#4ADE80]">Estimated win rate: ~{winWith}%</p>
              </div>
            </div>
          ) : null}

          {cost ? (
            <div className="elevated-card space-y-2 px-5 py-4 text-[13px]">
              <p className="eyebrow mb-2">Cost analysis</p>
              <p className="text-muted">
                False positive cost:{' '}
                <span className="font-mono text-ink">{formatRupees(cost.cost_per_false_positive)}</span> per
                failed contest
              </p>
              <p className="text-muted">
                False negative cost:{' '}
                <span className="font-mono text-ink">{formatRupees(cost.cost_per_false_negative)}</span> avg
                dispute amount
              </p>
              <p className="text-muted">
                Current threshold total cost:{' '}
                <span className="font-mono text-ink">{formatRupees(cost.current_threshold_total_cost)}</span>
              </p>
              <p className="text-muted">
                Optimal threshold ({cost.optimal_threshold}):{' '}
                <span className="font-mono text-ink">{formatRupees(cost.optimal_threshold_cost)}</span>
              </p>
              <p className="text-[#4ADE80]">
                Savings vs blind contest:{' '}
                <span className="font-mono">{formatRupees(cost.savings_vs_blind_contest)}</span>
              </p>
            </div>
          ) : null}

          {triage ? (
            <div>
              <p className="eyebrow mb-3">Triage distribution</p>
              <div className="flex h-4 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="bg-accent"
                  style={{ width: `${(triage.auto_submitted / triageTotal) * 100}%` }}
                  title={`Auto ${triage.auto_submitted}`}
                />
                <div
                  className="bg-warn"
                  style={{ width: `${(triage.sent_to_review / triageTotal) * 100}%` }}
                  title={`Review ${triage.sent_to_review}`}
                />
                <div
                  className="bg-white/20"
                  style={{ width: `${(triage.recommended_accept / triageTotal) * 100}%` }}
                  title={`Accept ${triage.recommended_accept}`}
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-4 text-[12px] text-muted">
                <span className="text-[#4ADE80]">Auto-submitted ({triage.auto_submitted})</span>
                <span className="text-[#FBBF24]">Review ({triage.sent_to_review})</span>
                <span>Accepted ({triage.recommended_accept})</span>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

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

function MetricCard({ label, value }) {
  return (
    <div className="elevated-card px-4 py-4 text-center">
      <p className={`font-mono text-[28px] font-bold ${metricTone(value)}`}>{Number(value).toFixed(2)}</p>
      <p className="mt-1 text-[12px] text-muted">{label}</p>
    </div>
  )
}

function MatrixCell({ tone, label, value }) {
  const bg =
    tone === 'green'
      ? 'bg-accent/10 border-accent/20'
      : tone === 'amber'
        ? 'bg-warn/10 border-warn/20'
        : 'bg-danger/10 border-danger/20'
  return (
    <div className={`rounded-card border px-4 py-4 ${bg}`}>
      <p className="font-mono text-[24px] font-bold text-ink">{value}</p>
      <p className="mt-1 text-[12px] text-muted">{label}</p>
    </div>
  )
}

function TrainingCard({ title, status, dataset, metrics, threshold, topFeatures }) {
  const m = metrics || {}
  const feats = Array.isArray(topFeatures) ? topFeatures : []
  const maxImp = Math.max(...feats.map((f) => Number(f.importance) || 0), 1e-9)
  return (
    <div className="elevated-card px-5 py-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-ink">{title}</p>
        <span
          className={`rounded-pill border px-2 py-0.5 text-[10px] uppercase ${
            status === 'loaded'
              ? 'border-accent/30 bg-accent/10 text-accent'
              : 'border-warn/40 bg-warn/10 text-[#FBBF24]'
          }`}
        >
          {status || 'unknown'}
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-muted">{dataset}</p>
      {status === 'loaded' ? (
        <>
          <p className="mt-2 text-[12px] text-muted">
            Features used: <span className="font-mono text-ink">{m.num_features ?? '—'}</span>
            {' · '}
            Training data:{' '}
            <span className="font-mono text-ink">
              {Number(m.dataset_size || 0).toLocaleString()} transactions
            </span>
          </p>
          <p className="mt-1 text-[12px] text-muted">
            Deploy threshold:{' '}
            <span className="font-mono text-ink">{Number(threshold ?? m.optimal_threshold ?? 0.5).toFixed(3)}</span>
          </p>
          <p className="mt-2 font-mono text-[12px] text-ink">
            Precision: {Number(m.precision || 0).toFixed(3)} | Recall:{' '}
            {Number(m.recall || 0).toFixed(3)} | F1: {Number(m.f1 || 0).toFixed(3)}
          </p>
          {feats.length > 0 ? (
            <div className="mt-3 space-y-1.5">
              <p className="text-[11px] uppercase tracking-[0.06em] text-label">Top features</p>
              {feats.slice(0, 5).map((f) => {
                const imp = Number(f.importance) || 0
                const pct = Math.max(4, Math.round((imp / maxImp) * 100))
                return (
                  <div key={f.name} className="grid grid-cols-[110px_1fr_44px] items-center gap-2">
                    <span className="truncate font-mono text-[10px] text-muted">{f.name}</span>
                    <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                      <div className="h-full rounded-full bg-accent/80" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-right font-mono text-[10px] text-label">{imp.toFixed(3)}</span>
                  </div>
                )
              })}
            </div>
          ) : null}
        </>
      ) : (
        <p className="mt-2 text-[12px] text-[#FBBF24]">Model file not loaded — run train scripts.</p>
      )}
    </div>
  )
}
