type Props = {
  label: string
  value: number | null | undefined
  suffix?: string
  max?: number
  decimals?: number
  help?: string
}
export default function StatBar({ label, value, suffix = '', max = 100, decimals = 1, help }: Props) {
  const valid = value !== null && value !== undefined && Number.isFinite(Number(value))
  const numeric = valid ? Number(value) : 0
  const pct = Math.max(0, Math.min(100, max > 0 ? (numeric / max) * 100 : 0))
  const formatted = valid ? numeric.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : '—'
  return (
    <div className="stat-bar-row">
      <div className="stat-bar-head">
        <span>{label}{help && <TooltipText text={help} />}</span>
        <strong>{formatted}{valid ? suffix : ''}</strong>
      </div>
      <div className="stat-track"><span style={{ width: `${pct}%` }} /></div>
    </div>
  )
}
function TooltipText({ text }: { text: string }) {
  return <span className="mini-help" title={text}>?</span>
}
