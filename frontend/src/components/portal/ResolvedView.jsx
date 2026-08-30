export default function ResolvedView({ resolution }) {
  const r = resolution || {}
  return (
    <div className="elevated-card space-y-3 border-accent/30 px-4 py-5">
      <p className="text-[16px] font-medium text-accent">Your issue has been resolved ✓</p>
      {r.amount != null ? (
        <p className="font-mono text-[14px] text-ink">
          Refund: ₹{Number(r.amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          {r.refundId ? ` · ${r.refundId}` : ''}
        </p>
      ) : null}
      {r.ticketId ? <p className="font-mono text-[14px] text-ink">Ticket: {r.ticketId}</p> : null}
      {r.detail ? <p className="text-[13px] leading-relaxed text-muted">{r.detail}</p> : null}
      <p className="text-[13px] text-muted">
        If you need further help, reply to your order confirmation email.
      </p>
      <p className="text-[11px] text-label">This interaction has been recorded for your protection</p>
    </div>
  )
}
