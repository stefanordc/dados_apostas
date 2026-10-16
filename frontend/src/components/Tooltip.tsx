type Props = { text: string }
export default function Tooltip({ text }: Props) {
  return (
    <span className="help-tip" tabIndex={0} aria-label={text}>
      ?
      <span className="help-tip-content">{text}</span>
    </span>
  )
}
