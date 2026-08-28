import { useEffect, useState } from 'react'
import { getMetrics } from '../lib/api'

const EMPTY = {
  total_disputes: 0,
  by_status: {},
  avg_processing_time_seconds: 0,
  evidence_coverage_rate: 0,
}

export default function MetricsSummary({ refreshKey = 0 }) {
  const [metrics, setMetrics] = useState(EMPTY)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await getMetrics()
        if (alive) {
          setMetrics(data)
          setError(null)
        }
      } catch (err) {
        if (alive) setError(err.message || 'Failed to load metrics')
      }
    }
    load()
    const id = setInterval(load, 5000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [refreshKey])

  const submitted =
    (metrics.by_status?.submitted || 0) +
    (metrics.by_status?.won || 0) +
    (metrics.by_status?.lost || 0)
  const errors = metrics.by_status?.error || 0
  const avg = Number(metrics.avg_processing_time_seconds || 0)
  const coverage = Number(metrics.evidence_coverage_rate || 0) * 100

  const cells = [
    { label: 'Total', value: String(metrics.total_disputes || 0), tone: 'text-ink' },
    { label: 'Submitted', value: String(submitted), tone: 'text-[#4ADE80]' },
    {
      label: 'Errors',
      value: String(errors),
      tone: errors === 0 ? 'text-[#4ADE80]' : 'text-[#F87171]',
    },
    { label: 'Avg Time', value: `${avg.toFixed(1)}s`, tone: 'text-ink' },
    { label: 'Coverage', value: `${coverage.toFixed(0)}%`, tone: 'text-ink' },
  ]

  return (
    <section className="surface-card overflow-hidden">
      <div className="border-b border-white/[0.06] px-6 py-4">
        <p className="eyebrow">Batch overview</p>
        <h2 className="mt-1 text-[20px] font-semibold tracking-[-0.02em]">Metrics summary</h2>
      </div>
      {error ? (
        <p className="px-6 py-4 text-sm text-[#F87171]">{error}</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-5">
          {cells.map((cell, i) => (
            <div
              key={cell.label}
              className={`px-6 py-5 ${i > 0 ? 'md:border-l md:border-white/[0.06]' : ''} ${i === 1 || i === 3 ? 'border-l border-white/[0.06]' : ''}`}
            >
              <div className={`font-mono text-2xl font-bold tabular-nums ${cell.tone}`}>
                {cell.value}
              </div>
              <div className="mt-2 text-[11px] uppercase tracking-[0.08em] text-label">
                {cell.label}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
