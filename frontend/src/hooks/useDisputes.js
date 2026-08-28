import { useCallback, useEffect, useRef, useState } from 'react'
import { getDisputes } from '../lib/api'
import { TERMINAL } from '../lib/format'

export default function useDisputes(refreshKey = 0) {
  const [disputes, setDisputes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timer = useRef(null)

  const load = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const data = await getDisputes({ limit: 50 })
      setDisputes(data.disputes || [])
      setError(null)
    } catch (err) {
      setError(err.message || 'Failed to load disputes')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(false)
    timer.current = setInterval(() => load(true), 5000)
    return () => clearInterval(timer.current)
  }, [load, refreshKey])

  // Keep polling list always — statuses can change for non-selected rows.
  // Detail panel stops its own poll when terminal.
  return { disputes, loading, error, reload: () => load(true), allTerminal: disputes.every((d) => TERMINAL.has(d.status)) }
}
