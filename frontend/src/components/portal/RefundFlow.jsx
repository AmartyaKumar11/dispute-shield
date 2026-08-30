import { useState } from 'react'
import { portalRefund } from '../../lib/api'

const REASONS = [
  'Product not received',
  'Product damaged or defective',
  'Wrong product received',
  'Changed my mind',
  'Charged incorrect amount',
  'Other',
]

const field =
  'mt-1 w-full rounded-pill border border-white/[0.08] bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-accent/50'
const labelCls = 'block text-[12px] font-medium text-muted'

export default function RefundFlow({ token, autoAvailable, onBack, onResolved }) {
  const [reason, setReason] = useState(REASONS[0])
  const [detail, setDetail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  return (
    <div className="elevated-card space-y-3 p-4">
      <button type="button" onClick={onBack} className="text-[13px] text-accent hover:underline">
        ← Back
      </button>
      <h2 className="text-[16px] font-medium text-ink">Request a refund</h2>
      {autoAvailable ? (
        <p className="text-[13px] text-accent">Eligible for instant auto-refund.</p>
      ) : (
        <p className="text-[13px] text-muted">This request will be reviewed by the merchant.</p>
      )}
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
        Details (optional)
        <textarea
          value={detail}
          maxLength={500}
          onChange={(e) => setDetail(e.target.value)}
          rows={3}
          className={field}
          placeholder="Tell us what happened"
        />
      </label>
      {error ? <p className="text-[13px] text-[#F87171]">{error}</p> : null}
      <button
        type="button"
        disabled={loading}
        onClick={async () => {
          try {
            setLoading(true)
            setError(null)
            const res = await portalRefund(token, { reason, detail: detail || undefined })
            onResolved({
              type: res.refund_type === 'auto' ? 'auto_refund' : 'manual_refund',
              detail: res.message,
              amount: res.refund_amount_rupees,
              refundId: res.refund_id,
            })
          } catch (err) {
            setError(err.message || 'Refund failed')
          } finally {
            setLoading(false)
          }
        }}
        className="w-full rounded-pill bg-accent px-4 py-3 text-[14px] font-medium text-page transition hover:bg-accent-hover disabled:opacity-60"
      >
        {loading ? 'Processing…' : 'Request refund'}
      </button>
    </div>
  )
}
