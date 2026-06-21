interface Props {
  text: string
  docType: string
}

export function CitationChip({ text, docType }: Props) {
  const preview = text.length > 100 ? text.slice(0, 100) + '…' : text
  return (
    <span
      title={text}
      className="inline-flex items-start gap-1 rounded border border-indigo-200 bg-indigo-50 text-indigo-800 px-2 py-1 text-xs font-mono leading-snug max-w-full"
    >
      <span className="font-bold shrink-0">§</span>
      <span className="italic">&ldquo;{preview}&rdquo;</span>
      <span className="text-indigo-500 shrink-0">— {docType}</span>
    </span>
  )
}
