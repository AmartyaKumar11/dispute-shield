import { formatDate } from '../lib/format'

function winTone(score) {
  if (score == null) return { text: 'text-muted', ring: 'border-white/20', bg: 'bg-white/5' }
  if (score > 70) return { text: 'text-[#4ADE80]', ring: 'border-accent/50', bg: 'bg-accent/10' }
  if (score >= 40) return { text: 'text-[#FBBF24]', ring: 'border-warn/50', bg: 'bg-warn/10' }
  return { text: 'text-[#F87171]', ring: 'border-danger/40', bg: 'bg-danger/10' }
}

export default function AIReasoning({ dispute }) {
  const strategy = dispute.evidence_strategy || {}
  const analysis = dispute.evidence_analysis || {}
  const gaps = strategy.evidence_gaps || []
  const required = strategy.required_evidence || []
  const recommended = strategy.recommended_evidence || []
  const collected = [...required, ...recommended].filter((f) => !gaps.includes(f))
  const strengths = analysis.strengths || []
  const weaknesses = analysis.weaknesses || []
  const recommendations = analysis.letter_recommendations || []
  const win = dispute.win_probability
  const tone = winTone(win)
  const letterMode = strategy.letter_fallback ? 'Fallback template' : 'LLM-generated'
  const submittedAt =
    dispute.processing_time_seconds != null
      ? `${formatDate(dispute.created_at)} · ${Number(dispute.processing_time_seconds).toFixed(1)}s`
      : formatDate(dispute.created_at)

  const steps = [
    {
      n: '01',
      title: 'Dispute classified',
      body: (
        <p className="text-[13px] text-ink">
          <span className="text-accent">{strategy.display_name || dispute.reason_code}</span>
          {strategy.description ? (
            <span className="text-muted"> — {strategy.description}</span>
          ) : null}
        </p>
      ),
    },
    {
      n: '02',
      title: 'Evidence gathered',
      body: (
        <div className="space-y-2 text-[13px]">
          <p className="text-[#4ADE80]">
            Collected: {collected.length ? collected.map(pretty).join(', ') : 'pending'}
          </p>
          {gaps.length ? (
            <p className="text-[#FBBF24]">Missing: {gaps.map(pretty).join(', ')}</p>
          ) : (
            <p className="text-muted">No evidence gaps detected.</p>
          )}
        </div>
      ),
    },
    {
      n: '03',
      title: 'Evidence analysis',
      body: analysis.overall_strength || strengths.length ? (
        <div className="space-y-3 text-[13px]">
          <p className="text-muted">
            Overall:{' '}
            <span className="font-mono capitalize text-ink">{analysis.overall_strength || '—'}</span>
            {analysis.used_fallback ? (
              <span className="ml-2 rounded-pill border border-warn/40 bg-warn/15 px-2 py-0.5 text-[11px] text-[#FBBF24]">
                Rule fallback
              </span>
            ) : null}
          </p>
          {strengths.length ? (
            <ul className="space-y-1">
              {strengths.map((s) => (
                <li key={s} className="text-[#4ADE80]">
                  + {s}
                </li>
              ))}
            </ul>
          ) : null}
          {weaknesses.length ? (
            <ul className="space-y-1">
              {weaknesses.map((s) => (
                <li key={s} className="text-[#F87171]">
                  − {s}
                </li>
              ))}
            </ul>
          ) : null}
          {recommendations.length ? (
            <ul className="space-y-1">
              {recommendations.map((s) => (
                <li key={s} className="text-[#60A5FA]">
                  → {s}
                </li>
              ))}
            </ul>
          ) : null}
          {analysis.confidence_notes ? (
            <p className="text-[12px] text-muted">{analysis.confidence_notes}</p>
          ) : null}
        </div>
      ) : (
        <p className="text-[13px] text-muted">Analysis pending…</p>
      ),
    },
    {
      n: '04',
      title: 'Win probability',
      body:
        win != null ? (
          <div className="flex flex-wrap items-center gap-4">
            <div
              className={`flex h-20 w-20 items-center justify-center rounded-full border-2 ${tone.ring} ${tone.bg}`}
            >
              <span className={`font-mono text-[22px] font-bold ${tone.text}`}>
                {Number(win).toFixed(0)}
              </span>
            </div>
            <p className="max-w-md text-[13px] leading-relaxed text-ink">
              {dispute.win_probability_reasoning || 'No reasoning available.'}
            </p>
          </div>
        ) : (
          <p className="text-[13px] text-muted">Score pending…</p>
        ),
    },
    {
      n: '05',
      title: 'Letter generated',
      body: (
        <p className="text-[13px] text-ink">
          {dispute.explanation_letter ? letterMode : 'Generating…'}
          {strategy.letter_fallback ? (
            <span className="ml-2 rounded-pill border border-warn/40 bg-warn/15 px-2 py-0.5 text-[11px] text-[#FBBF24]">
              Fallback
            </span>
          ) : dispute.explanation_letter ? (
            <span className="ml-2 rounded-pill border border-accent/30 bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
              LLM
            </span>
          ) : null}
        </p>
      ),
    },
    {
      n: '06',
      title: 'Contest submitted',
      body: (
        <p className="font-mono text-[13px] text-ink">
          {dispute.status === 'submitted' || dispute.status === 'won' || dispute.status === 'lost'
            ? submittedAt
            : dispute.status === 'error'
              ? 'Failed — see error below'
              : 'Awaiting submission…'}
        </p>
      ),
    },
  ]

  return (
    <section>
      <p className="eyebrow mb-3">AI Reasoning</p>
      <div className="relative space-y-3">
        <div className="absolute bottom-3 left-[27px] top-3 w-px bg-white/[0.08]" aria-hidden />
        {steps.map((step) => (
          <div key={step.n} className="relative flex gap-4">
            <div className="relative z-[1] flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white/[0.1] bg-elevated font-mono text-[12px] text-accent">
              {step.n}
            </div>
            <div className="elevated-card min-w-0 flex-1 px-4 py-3">
              <p className="text-[12px] font-medium uppercase tracking-[0.06em] text-label">{step.title}</p>
              <div className="mt-2">{step.body}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function pretty(name) {
  return String(name).replaceAll('_', ' ')
}
