import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { RiskBadge } from '../components/RiskBadge'
import { OpenSanctionsBadge } from '../components/OpenSanctionsBadge'
import { SyntheticBadge } from '../components/SyntheticBadge'
import type { FundSummary, HighRiskEntry } from '../types'

const TIER_COLOR: Record<string, string> = {
  low: 'border-green-300 bg-green-50 text-green-800',
  medium: 'border-yellow-300 bg-yellow-50 text-yellow-800',
  high: 'border-orange-300 bg-orange-50 text-orange-800',
  critical: 'border-red-300 bg-red-50 text-red-800',
}

function StatCard({
  label,
  value,
  sub,
  onClick,
  active,
}: {
  label: string
  value: number | string
  sub?: string
  onClick?: () => void
  active?: boolean
}) {
  return (
    <div
      className={`bg-white rounded-lg border p-4 shadow-sm transition-colors ${
        onClick ? 'cursor-pointer hover:bg-indigo-50 hover:border-indigo-300' : ''
      } ${active ? 'border-indigo-400 ring-2 ring-indigo-200' : 'border-gray-200'}`}
      onClick={onClick}
    >
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-sm font-medium text-gray-600 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  )
}

function TierCard({ tier, count }: { tier: string; count: number }) {
  return (
    <div className={`rounded-lg border p-4 ${TIER_COLOR[tier] ?? 'border-gray-200 bg-white text-gray-700'}`}>
      <div className="text-2xl font-bold">{count}</div>
      <div className="text-sm font-semibold uppercase mt-0.5">{tier}</div>
    </div>
  )
}

export function CommandCentre() {
  const navigate = useNavigate()
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.getDashboard,
  })
  const { data: funds } = useQuery({ queryKey: ['funds'], queryFn: api.getFunds })

  const [viewMode, setViewMode] = useState<'live' | 'all'>('live')
  const [showStatic, setShowStatic] = useState(false)

  const staticFunds = funds?.filter(f => f.synthetic_static) ?? []
  const liveFunds = funds?.filter(f => !f.synthetic_static) ?? []

  if (isLoading || !data) {
    return <div className="p-8 text-gray-500">Loading portfolio…</div>
  }

  return (
    <div className="p-8 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Command Centre</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Portfolio Pulse: {data.total_funds} Funds &middot; {data.live_funds} live-tracked &middot;{' '}
            {data.high_critical_count} High/Critical (Fund or BLE)
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="px-3 py-1.5 text-sm bg-white border border-gray-300 rounded-md shadow-sm hover:bg-gray-50"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Stat cards — Total Funds and Live Tracked toggle the lower view */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Total Funds"
          value={data.total_funds}
          sub="5 live + 45 static"
          onClick={() => setViewMode('all')}
          active={viewMode === 'all'}
        />
        <StatCard
          label="Live Tracked"
          value={data.live_funds}
          sub="Full AI pipeline"
          onClick={() => setViewMode('live')}
          active={viewMode === 'live'}
        />
        <StatCard label="High / Critical" value={data.high_critical_count} sub="Fund or BLE" />
        <StatCard label="Ruleset" value="v1" sub="Active" />
      </div>

      {/* Tier distribution */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        {['critical', 'high', 'medium', 'low'].map(tier => (
          <TierCard key={tier} tier={tier} count={data.tier_distribution[tier] ?? 0} />
        ))}
      </div>

      {viewMode === 'live' ? (
        /* ── Live Funds view ── */
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">Live Funds</h2>
            <span className="text-xs text-gray-400">{liveFunds.length} funds — full AI pipeline</span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-5 py-2 text-left">Fund Name</th>
                <th className="px-5 py-2 text-left">Country</th>
                <th className="px-5 py-2 text-center">BLEs</th>
                <th className="px-5 py-2 text-left">Direct Tier</th>
                <th className="px-5 py-2 text-left">Effective Tier</th>
                <th className="px-5 py-2 text-right">Score</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {liveFunds.map((f: FundSummary) => {
                const effectiveTier = f.escalated_tier ?? f.direct_tier
                const isEscalated = f.escalated_tier && f.escalated_tier !== f.direct_tier
                return (
                  <tr
                    key={f.fund_id}
                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => navigate(`/funds/${f.fund_id}`)}
                  >
                    <td className="px-5 py-3 font-medium text-gray-900">{f.name}</td>
                    <td className="px-5 py-3 text-gray-500">{f.incorporation_country}</td>
                    <td className="px-5 py-3 text-center font-mono text-gray-600">{f.bles.length}</td>
                    <td className="px-5 py-3">
                      <RiskBadge tier={f.direct_tier} size="sm" />
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1.5">
                        <RiskBadge tier={effectiveTier} size="sm" />
                        {isEscalated && (
                          <span className="text-xs text-red-500" title={f.escalation_reason ?? ''}>
                            ↑ escalated
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-gray-700">{f.direct_score}</td>
                    <td className="px-5 py-3 text-indigo-600 font-medium">→</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        /* ── All Funds view (original Command Centre) ── */
        <>
          {/* High-risk queue */}
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
              <h2 className="font-semibold text-gray-800">High-Risk Queue</h2>
              <span className="text-xs text-gray-400">{data.high_risk_queue.length} entries</span>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                <tr>
                  <th className="px-5 py-2 text-left">Fund</th>
                  <th className="px-5 py-2 text-left">Critical BLE</th>
                  <th className="px-5 py-2 text-left">Effective Tier</th>
                  <th className="px-5 py-2 text-left">Direct Score</th>
                  <th className="px-5 py-2 text-left">Trigger</th>
                  <th className="px-5 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.high_risk_queue.map((entry: HighRiskEntry) => (
                  <tr
                    key={entry.fund_id}
                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => navigate(`/funds/${entry.fund_id}`)}
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-gray-900">{entry.fund_name}</span>
                        <SyntheticBadge />
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      {entry.escalated_ble_name ? (
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-red-700 font-medium">{entry.escalated_ble_name}</span>
                          <RiskBadge tier="critical" size="sm" />
                          <OpenSanctionsBadge show={entry.escalated_ble_name.includes('Bank Rossiya')} />
                        </div>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <RiskBadge tier={entry.effective_tier} />
                    </td>
                    <td className="px-5 py-3 font-mono text-gray-700">{entry.direct_score}</td>
                    <td className="px-5 py-3 text-gray-500">
                      {entry.last_trigger_type ? entry.last_trigger_type.replace(/_/g, ' ') : '—'}
                    </td>
                    <td className="px-5 py-3 text-indigo-600 font-medium">→</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Static funds collapsed section */}
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
            <button
              className="w-full px-5 py-3 flex items-center justify-between text-sm font-semibold text-gray-700 hover:bg-gray-50 transition-colors"
              onClick={() => setShowStatic(v => !v)}
            >
              <span>Static Demo Funds ({staticFunds.length}) — view only, no AI pipeline</span>
              <span>{showStatic ? '▲' : '▼'}</span>
            </button>
            {showStatic && (
              <div className="border-t border-gray-100 max-h-64 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-xs text-gray-500 uppercase sticky top-0">
                    <tr>
                      <th className="px-5 py-2 text-left">Fund Name</th>
                      <th className="px-5 py-2 text-left">Country</th>
                      <th className="px-5 py-2 text-left">Tier</th>
                      <th className="px-5 py-2 text-right">Score</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {staticFunds.map(f => (
                      <tr
                        key={f.fund_id}
                        className="hover:bg-gray-50 cursor-pointer"
                        onClick={() => navigate(`/funds/${f.fund_id}`)}
                      >
                        <td className="px-5 py-2 text-gray-700">{f.name}</td>
                        <td className="px-5 py-2 text-gray-500">{f.incorporation_country}</td>
                        <td className="px-5 py-2">
                          <RiskBadge tier={f.direct_tier} size="sm" />
                        </td>
                        <td className="px-5 py-2 text-right font-mono text-gray-600">{f.direct_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
