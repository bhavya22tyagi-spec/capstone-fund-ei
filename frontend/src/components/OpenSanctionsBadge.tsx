interface Props {
  show: boolean
}

export function OpenSanctionsBadge({ show }: Props) {
  if (!show) return null
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 ring-1 ring-blue-300 px-2 py-0.5 text-xs font-semibold">
      <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z" clipRule="evenodd" />
      </svg>
      Real: OpenSanctions
    </span>
  )
}
