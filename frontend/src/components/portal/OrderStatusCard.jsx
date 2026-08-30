export default function OrderStatusCard({ order, shipping }) {
  const ship = shipping || {}
  const status = (ship.status || 'pending').toLowerCase()
  const badge =
    status === 'delivered'
      ? { cls: 'border-accent/30 bg-accent/10 text-accent', label: 'Delivered' }
      : status === 'in_transit'
        ? { cls: 'border-info/30 bg-info/10 text-[#60A5FA]', label: 'In transit' }
        : status === 'returned'
          ? { cls: 'border-danger/30 bg-danger/10 text-[#F87171]', label: 'Delivery failed' }
          : { cls: 'border-white/10 bg-white/5 text-muted', label: 'Processing' }

  const method = (order.payment_method || 'card').toLowerCase()

  return (
    <div className="elevated-card px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[12px] text-muted">Order #{order.order_id}</p>
          <p className="mt-1 text-[16px] font-medium text-ink">{order.product_name}</p>
          <p className="mt-1 text-[13px] text-muted">
            ₹{Number(order.amount_rupees || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            {' · '}
            {order.order_date ? new Date(order.order_date).toLocaleDateString() : '—'}
          </p>
        </div>
        <span
          className={`rounded-pill border px-2.5 py-1 text-[11px] font-medium uppercase ${
            method === 'upi'
              ? 'border-warn/30 bg-warn/10 text-[#FBBF24]'
              : 'border-info/30 bg-info/10 text-[#60A5FA]'
          }`}
        >
          {method === 'upi' ? 'UPI' : 'Card'}
        </span>
      </div>

      <div className="mt-4 border-t border-white/[0.06] pt-3">
        <span className={`inline-flex rounded-pill border px-2.5 py-1 text-[12px] font-medium ${badge.cls}`}>
          {badge.label}
        </span>
        <p className="mt-2 text-[13px] text-muted">
          {status === 'delivered' ? (
            <>
              Delivered{ship.delivered_at ? ` on ${new Date(ship.delivered_at).toLocaleDateString()}` : ''}
              {ship.signed_by ? `, signed by ${ship.signed_by}` : ''}
              {ship.carrier ? ` · ${ship.carrier}` : ''}
            </>
          ) : status === 'in_transit' ? (
            <>
              In transit via {ship.carrier || 'courier'}
              {ship.tracking_id ? ` · Tracking ${ship.tracking_id}` : ''}
            </>
          ) : status === 'returned' ? (
            <>Delivery failed — we&apos;re sorry about this. A refund is recommended.</>
          ) : (
            <>Processing — shipment not yet dispatched</>
          )}
        </p>
      </div>
    </div>
  )
}
