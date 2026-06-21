interface Props {
  factorScores: Record<string, number>
  maxScore?: number
}

const FACTOR_COLORS: Record<string, string> = {
  Country:   'bg-blue-500',
  Screening: 'bg-red-500',
  PEP:       'bg-purple-500',
  UBO:       'bg-orange-500',
  Documents: 'bg-yellow-500',
  default:   'bg-gray-400',
}

export function ScoreBar({ factorScores, maxScore = 30 }: Props) {
  const entries = Object.entries(factorScores)
  if (entries.length === 0) return <p className="text-sm text-gray-400 italic">No factor breakdown available.</p>

  return (
    <div className="space-y-2">
      {entries.map(([factor, score]) => {
        const pct = Math.min(100, (score / maxScore) * 100)
        const color = FACTOR_COLORS[factor] ?? FACTOR_COLORS.default
        return (
          <div key={factor} className="flex items-center gap-3">
            <span className="w-24 text-xs text-gray-600 shrink-0">{factor}</span>
            <div className="flex-1 h-3 rounded-full bg-gray-100 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${color}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-10 text-right text-xs text-gray-700 font-mono">{score.toFixed(1)}</span>
          </div>
        )
      })}
    </div>
  )
}
