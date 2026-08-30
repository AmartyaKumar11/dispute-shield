import { useEffect, useState } from 'react'
import { getPortalStatus } from '../../lib/api'
import OrderStatusCard from './OrderStatusCard'
import RefundFlow from './RefundFlow'
import ReplacementFlow from './ReplacementFlow'
import ChatInterface from './ChatInterface'
import ResolvedView from './ResolvedView'

export default function PortalPage({ token }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [view, setView] = useState('overview')
  const [resolution, setResolution] = useState(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        setLoading(true)
        const status = await getPortalStatus(token)
        if (!alive) return
        if (!status.valid) {
          setError(status.error || 'This link is invalid or expired')
          setData(null)
        } else {
          setData(status)
          setError(null)
          if (
            status.session_status?.startsWith('resolved') ||
            status.session_status === 'pending_merchant_review'
          ) {
            setView('resolved')
            setResolution({
              type: status.resolution_type || status.session_status,
              detail: status.resolution_detail,
              amount: status.refund_amount_rupees,
            })
          }
        }
      } catch (err) {
        if (alive) setError(err.message || 'Failed to load portal')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [token])

  const onResolved = (payload) => {
    setResolution(payload)
    setView('resolved')
  }

  return (
    <div className="min-h-screen bg-page text-ink">
      <header className="border-b border-white/[0.06] bg-page">
        <div className="mx-auto flex h-14 max-w-[520px] items-center px-6">
          <div className="display-title text-[28px] leading-none">DisputeShield</div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[520px] space-y-6 px-6 py-8">
        <div>
          <p className="eyebrow">Customer self-service</p>
          <h1 className="mt-1 text-[22px] font-medium">Order resolution center</h1>
          {data?.merchant_name ? (
            <p className="mt-1 text-[13px] text-muted">{data.merchant_name}</p>
          ) : null}
        </div>

        {loading ? (
          <p className="elevated-card px-4 py-8 text-center text-sm text-muted">Loading your order…</p>
        ) : error ? (
          <p className="elevated-card border-danger/30 px-4 py-8 text-center text-sm text-[#F87171]">
            {error}
          </p>
        ) : data ? (
          <div className="space-y-4 animate-fadeIn">
            <OrderStatusCard order={data.order} shipping={data.shipping} />

            {view === 'overview' ? (
              <div className="space-y-3">
                <p className="text-[13px] font-medium text-ink">How can we help?</p>
                <ActionBtn label="I want a refund" onClick={() => setView('refund')} />
                <ActionBtn label="I want a replacement" onClick={() => setView('replacement')} />
                <ActionBtn label="Chat with support" onClick={() => setView('chat')} />
              </div>
            ) : null}

            {view === 'refund' ? (
              <RefundFlow
                token={token}
                autoAvailable={data.auto_refund_available}
                onBack={() => setView('overview')}
                onResolved={onResolved}
              />
            ) : null}

            {view === 'replacement' ? (
              <ReplacementFlow
                token={token}
                onBack={() => setView('overview')}
                onResolved={onResolved}
              />
            ) : null}

            {view === 'chat' ? (
              <ChatInterface
                token={token}
                initialHistory={data.chat_history || []}
                onBack={() => setView('overview')}
                onResolved={onResolved}
              />
            ) : null}

            {view === 'resolved' ? <ResolvedView resolution={resolution} /> : null}
          </div>
        ) : null}

        <p className="pt-4 text-center text-[11px] text-label">Powered by DisputeShield</p>
      </main>
    </div>
  )
}

function ActionBtn({ label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="elevated-card w-full px-4 py-4 text-left text-[15px] font-medium text-ink transition hover:border-accent/40 hover:bg-white/[0.03]"
    >
      {label}
    </button>
  )
}
