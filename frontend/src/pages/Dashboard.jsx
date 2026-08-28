import { useState } from 'react'
import DisputeDetail from '../components/DisputeDetail'
import DisputeList from '../components/DisputeList'
import MetricsSummary from '../components/MetricsSummary'
import useDisputes from '../hooks/useDisputes'
import { seedDisputes } from '../lib/api'

export default function Dashboard() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [selectedId, setSelectedId] = useState(null)
  const [seeding, setSeeding] = useState(false)
  const [seedError, setSeedError] = useState(null)
  const { disputes, loading, error, reload } = useDisputes(refreshKey)

  const selectedStillThere = disputes.some((d) => d.id === selectedId)
  const activeId = selectedStillThere ? selectedId : disputes[0]?.id || null

  async function onSeed() {
    try {
      setSeeding(true)
      setSeedError(null)
      await seedDisputes()
      setRefreshKey((k) => k + 1)
      await reload()
    } catch (err) {
      setSeedError(err.message || 'Seed failed')
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="min-h-screen bg-page text-ink">
      <header className="sticky top-0 z-20 h-14 border-b border-white/[0.06] bg-page">
        <div className="mx-auto flex h-full max-w-shell items-center justify-between px-6">
          <div className="text-[18px] font-semibold tracking-[-0.02em]">DisputeShield</div>
          <button
            type="button"
            onClick={onSeed}
            disabled={seeding}
            className="inline-flex items-center gap-2 rounded-pill bg-accent px-5 py-[10px] text-[13px] font-medium text-page transition-colors duration-150 hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-70"
          >
            {seeding ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-page/30 border-t-page" />
                Seeding...
              </>
            ) : (
              'Seed Test Data'
            )}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-shell space-y-8 px-6 py-8">
        <div>
          <p className="eyebrow">AI risk manager</p>
          <h1 className="mt-2 text-[28px] font-semibold tracking-[-0.02em]">
            Chargeback evidence auto-assembler
          </h1>
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-muted">
            Watch disputes move from webhook to contested evidence package — strategy, shipping
            mocks, LLM letter, and submission status in one view.
          </p>
          {seedError ? <p className="mt-3 text-sm text-[#F87171]">{seedError}</p> : null}
        </div>

        <MetricsSummary refreshKey={refreshKey} />

        <section className="grid grid-cols-1 gap-3 lg:grid-cols-[2fr_3fr]">
          <div className="surface-card overflow-hidden">
            <div className="border-b border-white/[0.06] px-5 py-4">
              <p className="eyebrow">Incoming disputes</p>
              <h2 className="mt-1 text-[15px] font-medium">Dispute list</h2>
            </div>
            <DisputeList
              disputes={disputes}
              loading={loading}
              selectedId={activeId}
              onSelect={setSelectedId}
              error={error}
            />
          </div>

          <div className="surface-card min-h-[520px] overflow-hidden">
            <DisputeDetail
              disputeId={activeId}
              onRetried={() => {
                setRefreshKey((k) => k + 1)
                reload()
              }}
            />
          </div>
        </section>
      </main>
    </div>
  )
}
