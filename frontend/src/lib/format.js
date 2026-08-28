export const TERMINAL = new Set(['submitted', 'won', 'lost', 'error'])

export function formatRupees(amount) {
  const n = Number(amount ?? 0)
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

export function truncateId(id, keep = 10) {
  if (!id) return '—'
  if (id.length <= keep + 4) return id
  return `${id.slice(0, keep)}…`
}

export function evidenceChecklist(dispute) {
  const strategy = dispute?.evidence_strategy || {}
  const required = strategy.required_evidence || []
  const recommended = strategy.recommended_evidence || []
  const gaps = strategy.evidence_gaps || []
  const fields = [...new Set([...required, ...recommended, ...gaps])]
  const gapSet = new Set(gaps)
  const progressed = ['assembled', 'submitting', 'submitted', 'won', 'lost'].includes(dispute?.status)

  return fields.map((name) => {
    if (gapSet.has(name)) return { name, state: 'gap' }
    if (name === 'explanation_letter' && dispute?.explanation_letter) {
      return { name, state: 'collected' }
    }
    if (progressed) return { name, state: 'collected' }
    return { name, state: 'na' }
  })
}
