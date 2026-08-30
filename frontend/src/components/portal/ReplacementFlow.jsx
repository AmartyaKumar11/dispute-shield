import { useState } from 'react'
import { portalReplacement } from '../../lib/api'

const REASONS = [
  'Product damaged or defective',
  'Wrong product received',
  'Product not as described',
  'Other',
]

const field =
  'mt-1 w-full rounded-pill border border-white/[0.08] bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-accent/50'
const labelCls = 'block text-[12px] font-medium text-muted'

export default function ReplacementFlow({ token, onBack, onResolved }) {
  const [reason, setReason] = useState(REASONS[0])
  const [detail, setDetail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  return (
    <div className="elevated-card space-y-3 p-4">
      <button type="button" onClick={onBack} className="text-[13px] text-accent hover:underline">
        ← Back
      </button>
      <h2 className="text-[16px] font-medium text-ink">Request a replacement</h2>
      <label className={labelCls}>
        Reason
        <select value={reason} onChange={(e) => setReason(e.target.value)} className={field}>
          {REASONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <label className={labelCls}>
        Details (required, min 20 characters)
        <textarea
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          rows={4}
          className={field}
          placeholder="Describe the issue with the product"
        />
      </label>
      {error ? <p className="text-[13px] text-[#F87171]">{error}</p> : null}
      <button
        type="button"
        disabled={loading || detail.trim().length < 20}
        onClick={async () => {
          try {
            setLoading(true)
            setError(null)
            const res = await portalReplacement(token, { reason, detail })
            onResolved({
              type: 'replacement',
              detail: res.message,
              ticketId: res.ticket_id,
            })
          } catch (err) {
            setError(err.message || 'Request failed')
          } finally {
            setLoading(false)
          }
        }}
        className="w-full rounded-pill bg-accent px-4 py-3 text-[14px] font-medium text-page transition hover:bg-accent-hover disabled:opacity-60"
      >
        {loading ? 'Submitting…' : 'Request replacement'}
      </button>
    </div>
  )
}
