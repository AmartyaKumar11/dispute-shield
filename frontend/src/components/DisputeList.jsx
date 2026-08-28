import { formatRupees, truncateId } from '../lib/format'
import StatusBadge from './StatusBadge'

export default function DisputeList({
  disputes,
  loading,
  selectedId,
  onSelect,
  error,
}) {
  if (loading && !disputes.length) {
    return (
      <div className="space-y-2 p-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-16 animate-pulse rounded-pill bg-elevated" />
        ))}
      </div>
    )
  }

  if (error) {
    return <p className="p-6 text-sm text-[#F87171]">{error}</p>
  }

  if (!disputes.length) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-muted">
          No disputes yet. Click <span className="text-ink">Seed Test Data</span> to generate test
          disputes.
        </p>
      </div>
    )
  }

  return (
    <div className="max-h-[min(640px,70vh)] overflow-y-auto">
      {disputes.map((d, index) => {
        const selected = d.id === selectedId
        const secs = d.processing_time_seconds
        const display =
          d.evidence_strategy?.display_name || d.reason_code.replaceAll('_', ' ')
        return (
          <button
            key={d.id}
            type="button"
            onClick={() => onSelect(d.id)}
            style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }}
            className={`group flex w-full items-center gap-3 border-b border-white/[0.06] px-4 py-3.5 text-left transition-colors duration-150 animate-fadeIn hover:bg-elevated ${
              selected ? 'border-l-2 border-l-accent bg-elevated' : 'border-l-2 border-l-transparent'
            }`}
          >
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${
                d.status === 'error' || d.status === 'lost'
                  ? 'bg-danger'
                  : d.status === 'submitted' || d.status === 'won'
                    ? 'bg-accent'
                    : d.status === 'gathering' || d.status === 'submitting'
                      ? 'bg-info animate-pulseSoft'
                      : d.status === 'assembled'
                        ? 'bg-warn'
                        : 'bg-muted'
              }`}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[13px] text-ink">{truncateId(d.id)}</span>
                <StatusBadge status={d.status} triage={d.triage_action} />
                {d.win_probability != null ? (
                  <span
                    className={`font-mono text-[11px] ${
                      d.win_probability > 70
                        ? 'text-[#4ADE80]'
                        : d.win_probability >= 40
                          ? 'text-[#FBBF24]'
                          : 'text-[#F87171]'
                    }`}
                  >
                    {Number(d.win_probability).toFixed(0)}%
                  </span>
                ) : null}
              </div>
              <div className="mt-1.5">
                <span className="rounded-pill border border-white/[0.08] bg-page px-2 py-0.5 text-[11px] capitalize text-muted">
                  {display}
                </span>
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="font-mono text-[13px] text-ink">{formatRupees(d.amount_rupees)}</div>
              <div className="mt-1 text-[11px] text-muted">
                {secs == null ? '—' : `${Number(secs).toFixed(1)}s`}
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
