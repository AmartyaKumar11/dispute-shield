import { Check, X } from 'lucide-react'

const STEPS = [
  { key: 'received', label: 'Received' },
  { key: 'gathering', label: 'Gathering' },
  { key: 'assembled', label: 'Assembled' },
  { key: 'submitted', label: 'Submitted' },
  { key: 'verdict', label: 'Verdict' },
]

function statusIndex(status) {
  const map = {
    received: 0,
    gathering: 1,
    assembled: 2,
    submitting: 3,
    submitted: 3,
    won: 4,
    lost: 4,
    error: -1,
  }
  return map[status] ?? 0
}

export default function EvidenceTimeline({ status, createdAt, completedAt }) {
  const current = statusIndex(status)
  const isError = status === 'error'
  const failedAt = isError ? Math.max(current, 1) : -1

  return (
    <div className="px-1 py-2">
      <div className="flex items-start">
        {STEPS.map((step, i) => {
          let state = 'pending'
          if (isError && i === failedAt) state = 'error'
          else if (isError && i < failedAt) state = 'done'
          else if (!isError && i < current) state = 'done'
          else if (!isError && i === current) state = 'active'
          else if (!isError && current === 4 && i <= 4) state = i < 4 ? 'done' : 'active'

          if (status === 'submitted' && i === 3) state = 'done'
          if (status === 'submitted' && i === 4) state = 'pending'
          if ((status === 'won' || status === 'lost') && i <= 4) state = i < 4 ? 'done' : 'active'

          const lineDone =
            (!isError && i < current) ||
            (status === 'submitted' && i < 3) ||
            ((status === 'won' || status === 'lost') && i < 4) ||
            (isError && i < failedAt)

          return (
            <div key={step.key} className="flex flex-1 items-start last:flex-none">
              <div className="flex w-[72px] flex-col items-center text-center">
                <StepDot state={state} />
                <span className="mt-2 text-[11px] text-muted">{step.label}</span>
                {i === 0 && createdAt ? (
                  <span className="mt-1 font-mono text-[10px] text-label">{createdAt}</span>
                ) : null}
                {i === 3 && completedAt && ['submitted', 'won', 'lost'].includes(status) ? (
                  <span className="mt-1 font-mono text-[10px] text-label">{completedAt}</span>
                ) : null}
              </div>
              {i < STEPS.length - 1 ? (
                <div
                  className={`mt-2 h-px flex-1 ${lineDone ? 'bg-accent' : 'bg-white/10'} transition-colors duration-300`}
                />
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StepDot({ state }) {
  if (state === 'done') {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-accent text-page transition-colors duration-300">
        <Check size={10} strokeWidth={3} />
      </span>
    )
  }
  if (state === 'active') {
    return <span className="h-4 w-4 rounded-full bg-info animate-pulseGlow" />
  }
  if (state === 'error') {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-danger text-ink">
        <X size={10} strokeWidth={3} />
      </span>
    )
  }
  return <span className="h-4 w-4 rounded-full border border-white/15 bg-transparent" />
}
