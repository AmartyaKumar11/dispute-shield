import { useEffect, useRef, useState } from 'react'
import { portalChat } from '../../lib/api'

export default function ChatInterface({ token, initialHistory, onBack, onResolved }) {
  const [messages, setMessages] = useState(initialHistory || [])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text) => {
    const message = (text || '').trim()
    if (!message || loading) return
    setInput('')
    setSuggestions([])
    setMessages((prev) => [...prev, { role: 'customer', message, timestamp: new Date().toISOString() }])
    try {
      setLoading(true)
      const res = await portalChat(token, message)
      setMessages((prev) => [
        ...prev,
        { role: 'agent', message: res.reply, timestamp: new Date().toISOString() },
      ])
      setSuggestions(res.suggested_actions || [])
      if (res.resolution_detected) {
        onResolved({
          type: res.resolution_type || 'info_provided',
          detail: res.reply,
        })
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'agent',
          message:
            "I'm having trouble processing your request right now. Please use the refund or replacement buttons.",
          timestamp: new Date().toISOString(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="elevated-card flex h-[420px] flex-col">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2">
        <button type="button" onClick={onBack} className="text-[13px] text-accent hover:underline">
          ← Back
        </button>
        <p className="text-[13px] font-medium text-ink">Support chat</p>
        <span className="w-10" />
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === 'customer' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-card px-3 py-2 text-[13px] leading-relaxed ${
                m.role === 'customer'
                  ? 'bg-accent text-page'
                  : 'border border-white/[0.06] bg-surface text-ink'
              }`}
            >
              {m.message}
            </div>
          </div>
        ))}
        {loading ? (
          <div className="flex justify-start">
            <div className="rounded-card border border-white/[0.06] bg-surface px-3 py-2 text-[13px] text-muted">
              Typing…
            </div>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>
      {suggestions.length ? (
        <div className="flex flex-wrap gap-2 border-t border-white/[0.06] px-3 py-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => send(s)}
              className="rounded-pill border border-accent/30 bg-accent/10 px-3 py-1 text-[12px] text-accent"
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
      <form
        className="flex gap-2 border-t border-white/[0.06] p-2"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe your issue…"
          className="flex-1 rounded-pill border border-white/[0.08] bg-surface px-3 py-2 text-[14px] text-ink outline-none focus:border-accent/50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-pill bg-accent px-3 py-2 text-[13px] font-medium text-page hover:bg-accent-hover disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  )
}
