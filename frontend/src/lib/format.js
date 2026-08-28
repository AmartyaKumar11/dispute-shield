export const TERMINAL = new Set(['submitted', 'won', 'lost', 'error'])

const RUPEE = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const DATE = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
})

export function formatRupees(amount) {
  return RUPEE.format(Number(amount ?? 0))
}

export function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  // "28 Aug 2026, 2:30 pm" → normalize am/pm casing
  return DATE.format(d).replace(/\b(am|pm)\b/i, (m) => m.toUpperCase())
}

/** Truncate like disp_sim…01 — keep prefix + last 2 chars. */
export function truncateId(id) {
  if (!id) return '—'
  if (id.length <= 14) return id
  return `${id.slice(0, 8)}…${id.slice(-2)}`
}

export function evidenceChecklist(dispute) {
  const strategy = dispute?.evidence_strategy || {}
  const required = strategy.required_evidence || []
  const recommended = strategy.recommended_evidence || []
  const gaps = strategy.evidence_gaps || []
  const fields = [...new Set([...required, ...recommended, ...gaps])]
  const gapSet = new Set(gaps)
  const progressed = ['assembled', 'submitting', 'submitted', 'won', 'lost'].includes(
    dispute?.status,
  )

  return fields.map((name) => {
    if (gapSet.has(name)) return { name, state: 'gap' }
    if (name === 'explanation_letter' && dispute?.explanation_letter) {
      return { name, state: 'collected' }
    }
    if (progressed) return { name, state: 'collected' }
    return { name, state: 'na' }
  })
}
