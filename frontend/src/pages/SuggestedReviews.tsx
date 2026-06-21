import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { SuggestionItem } from '../types'

function ScopePill({ scope }: { scope: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
      scope === 'fund' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
    }`}>
      {scope.toUpperCase()}
    </span>
  )
}

export function SuggestedReviews() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [fadedOut, setFadedOut] = useState<Set<string>>(new Set())
  const actor = 'compliance.officer@fundei.internal'

  const { data: suggestions = [], isLoading } = useQuery({
    queryKey: ['suggestions'],
    queryFn: () => api.getSuggestions('pending'),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['suggestions'] })
    setSelected(new Set())
  }

  const fade = (id: string) => setFadedOut(prev => new Set([...prev, id]))

  const acceptMut = useMutation({
    mutationFn: (id: string) => api.acceptSuggestion(id, { actor }),
    onSuccess: (_, id) => { fade(id); setTimeout(invalidate, 400) },
  })
  const declineMut = useMutation({
    mutationFn: (id: string) => api.declineSuggestion(id, { actor }),
    onSuccess: (_, id) => { fade(id); setTimeout(invalidate, 400) },
  })
  const bulkAcceptMut = useMutation({
    mutationFn: () => api.bulkAccept({ ids: [...selected], actor }),
    onSuccess: () => { [...selected].forEach(fade); setTimeout(invalidate, 400) },
  })
  const bulkDeclineMut = useMutation({
    mutationFn: () => api.bulkDecline({ ids: [...selected], actor }),
    onSuccess: () => { [...selected].forEach(fade); setTimeout(invalidate, 400) },
  })

  const pending = suggestions.filter((s: SuggestionItem) => s.status === 'pending')
  const allIds = pending.map((s: SuggestionItem) => s.suggestion_id)
  const allSelected = allIds.length > 0 && allIds.every((id: string) => selected.has(id))

  const toggleAll = () => {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(allIds))
  }
  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (isLoading) return <div className="p-8 text-gray-500">Loading reviews…</div>

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Suggested Reviews</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {pending.length} pending &middot; All decisions require human Accept / Decline
          </p>
        </div>
        {selected.size > 0 && (
          <div className="flex gap-2">
            <button
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
              disabled={bulkAcceptMut.isPending}
              onClick={() => bulkAcceptMut.mutate()}
            >
              ✓ Accept ({selected.size})
            </button>
            <button
              className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50"
              disabled={bulkDeclineMut.isPending}
              onClick={() => bulkDeclineMut.mutate()}
            >
              ✕ Decline ({selected.size})
            </button>
          </div>
        )}
      </div>

      {pending.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <div className="text-4xl mb-3">✓</div>
          <div className="text-lg font-medium">All clear — no pending reviews</div>
          <div className="text-sm mt-1">The compliance queue is empty.</div>
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-4 py-2 w-8">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll} className="rounded" />
                </th>
                <th className="px-4 py-2 text-left">Scope</th>
                <th className="px-4 py-2 text-left">Fund / BLE</th>
                <th className="px-4 py-2 text-left">Trigger</th>
                <th className="px-4 py-2 text-left">What Changed</th>
                <th className="px-4 py-2 text-left">Date</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {pending.map((s: SuggestionItem) => (
                <tr
                  key={s.suggestion_id}
                  className={`transition-all duration-300 ${
                    fadedOut.has(s.suggestion_id) ? 'opacity-0' : 'opacity-100'
                  } hover:bg-gray-50`}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected.has(s.suggestion_id)}
                      onChange={() => toggle(s.suggestion_id)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <ScopePill scope={s.scope} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900">{s.fund_name}</div>
                    {s.ble_name && (
                      <div className="text-xs text-purple-600 mt-0.5">
                        ↑ BLE: {s.ble_name}
                      </div>
                    )}
                    {s.cascade_info && (
                      <div className="text-xs text-amber-600 mt-0.5">
                        ↑ Escalated from BLE: {s.cascade_info.ble_name ?? s.ble_name}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {s.trigger_type.replace(/_/g, ' ')}
                  </td>
                  <td className="px-4 py-3 text-gray-500 max-w-xs">
                    {s.what_changed_summary}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                    {new Date(s.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1.5">
                      <button
                        className="px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                        disabled={acceptMut.isPending}
                        onClick={() => acceptMut.mutate(s.suggestion_id)}
                      >
                        Accept
                      </button>
                      <button
                        className="px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200 disabled:opacity-50"
                        disabled={declineMut.isPending}
                        onClick={() => declineMut.mutate(s.suggestion_id)}
                      >
                        Decline
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
