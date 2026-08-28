const STYLES = {
  received: 'bg-white/[0.06] text-muted',
  gathering: 'bg-info/15 text-[#60A5FA] animate-pulseSoft',
  assembled: 'bg-warn/15 text-[#FBBF24]',
  submitting: 'bg-info/15 text-[#60A5FA] animate-pulseSoft',
  submitted: 'bg-accent/15 text-[#4ADE80]',
  won: 'bg-accent/20 text-accent font-semibold',
  lost: 'bg-danger/15 text-[#F87171]',
  error: 'bg-danger/15 text-[#F87171]',
}

export default function StatusBadge({ status }) {
  const key = (status || 'received').toLowerCase()
  return (
    <span
      className={`inline-flex items-center rounded-pill px-2.5 py-1 text-[11px] uppercase tracking-[0.06em] ${STYLES[key] || STYLES.received}`}
    >
      {key}
    </span>
  )
}
