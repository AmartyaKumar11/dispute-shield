export default function ExplanationPreview({ text, loading }) {
  if (loading) return <p className="text-sm text-muted">Generating…</p>
  return (
    <pre className="whitespace-pre-wrap font-sans text-[14px] leading-[1.7] text-ink">{text}</pre>
  )
}
