import type { RiskTier } from '../types'

const TIER_STYLES: Record<string, string> = {
  low:      'bg-green-100 text-green-800 ring-1 ring-green-300',
  medium:   'bg-yellow-100 text-yellow-800 ring-1 ring-yellow-300',
  high:     'bg-orange-100 text-orange-800 ring-1 ring-orange-300',
  critical: 'bg-red-100 text-red-800 ring-1 ring-red-300',
}

interface Props {
  tier: RiskTier | string
  score?: number
  size?: 'sm' | 'md' | 'lg'
}

export function RiskBadge({ tier, score, size = 'md' }: Props) {
  const cls = TIER_STYLES[tier] ?? 'bg-gray-100 text-gray-700 ring-1 ring-gray-300'
  const padding = size === 'sm' ? 'px-1.5 py-0.5 text-xs' : size === 'lg' ? 'px-3 py-1 text-base' : 'px-2 py-0.5 text-sm'
  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-semibold uppercase ${padding} ${cls}`}>
      {tier.toUpperCase()}
      {score !== undefined && <span className="font-normal opacity-70">({score})</span>}
    </span>
  )
}
