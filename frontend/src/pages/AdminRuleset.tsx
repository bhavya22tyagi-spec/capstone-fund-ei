import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ScreeningResult } from '../api/client'
import type { RulesetConfig } from '../types'

const WEIGHT_FIELDS: Array<{ key: keyof RulesetConfig; label: string }> = [
  { key: 'weight_country', label: 'Country Risk' },
  { key: 'weight_screening', label: 'Screening / Sanctions' },
  { key: 'weight_pep', label: 'PEP Exposure' },
  { key: 'weight_ubo', label: 'UBO Chain Complexity' },
  { key: 'weight_documents', label: 'Document Currency' },
]

function pct(v: number) { return `${v.toFixed(0)}%` }

export function AdminRuleset() {
  const navigate = useNavigate()
  const { data: remote, isLoading } = useQuery({
    queryKey: ['ruleset'],
    queryFn: api.getRuleset,
  })

  const [form, setForm] = useState<RulesetConfig | null>(null)
  const [toast, setToast] = useState('')
  const [screeningResult, setScreeningResult] = useState<ScreeningResult | null>(null)
  const [screeningError, setScreeningError] = useState<string | null>(null)

  useEffect(() => {
    if (remote && !form) setForm(remote)
  }, [remote, form])

  const publishMut = useMutation({
    mutationFn: (cfg: RulesetConfig) => api.publishRuleset(cfg),
    onSuccess: (updated) => {
      setForm(updated)
      setToast(`Published — Ruleset ${updated.version}`)
      setTimeout(() => setToast(''), 3000)
    },
  })

  const screeningMut = useMutation({
    mutationFn: () => api.runScreening(),
    onSuccess: (data) => {
      setScreeningResult(data)
      setScreeningError(null)
    },
    onError: (err: Error) => {
      setScreeningError(err.message)
      setScreeningResult(null)
    },
  })

if (isLoading || !form) return <div className="p-8 text-gray-500">Loading ruleset…</div>

  const total = WEIGHT_FIELDS.reduce((s, f) => s + (form[f.key] as number), 0)
  const totalValid = Math.abs(total - 100) < 0.1

  const setWeight = (key: keyof RulesetConfig, val: number) => {
    setForm(prev => prev ? { ...prev, [key]: val } : prev)
  }

  return (
    <div className="p-8 max-w-2xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Ruleset Builder</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Configure risk weights and scoring behaviour. Version {form.version}.
        </p>
      </div>

      {toast && (
        <div className="mb-4 px-4 py-2.5 bg-green-50 border border-green-200 text-green-800 text-sm rounded-lg">
          ✓ {toast}
        </div>
      )}

      {/* Scope */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5 mb-4">
        <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">Scope Level</div>
        <div className="flex gap-4">
          {['fund', 'ble', 'both'].map(s => (
            <label key={s} className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="scope"
                value={s}
                checked={form.scope_level === s}
                onChange={() => setForm(prev => prev ? { ...prev, scope_level: s } : prev)}
                className="text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm capitalize text-gray-700">{s}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Weight sliders */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5 mb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Risk Weights</div>
          <div className={`text-sm font-bold ${totalValid ? 'text-green-600' : 'text-red-600'}`}>
            Total: {pct(total)} {totalValid ? '✓' : '≠ 100'}
          </div>
        </div>
        <div className="space-y-5">
          {WEIGHT_FIELDS.map(({ key, label }) => {
            const val = form[key] as number
            return (
              <div key={key}>
                <div className="flex justify-between mb-1">
                  <span className="text-sm text-gray-700">{label}</span>
                  <span className="text-sm font-mono font-semibold text-gray-800">{pct(val)}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={val}
                  onChange={e => setWeight(key, parseInt(e.target.value, 10))}
                  className="w-full accent-indigo-600"
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Toggles */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5 mb-6">
        <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-4">
          Hard-Wired Rules (PRD §9.3 — non-negotiable)
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-gray-800">Hard Stop</div>
              <div className="text-xs text-gray-500">Block onboarding when score exceeds critical threshold</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full font-semibold">ON</span>
              <span className="text-xs text-gray-400">(always enabled)</span>
            </div>
          </div>
          <div className="border-t border-gray-100 pt-4 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-gray-800">BLE → Fund Escalation</div>
              <div className="text-xs text-gray-500">Critical BLE automatically surfaces Fund as Critical</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full font-semibold">ON</span>
              <span className="text-xs text-gray-400">(always enabled)</span>
            </div>
          </div>
        </div>
        <div className="mt-3 text-xs text-amber-700 bg-amber-50 rounded p-2.5">
          These rules are deterministic code — not configurable via UI per PRD §9.3.
        </div>
      </div>

      {/* Publish */}
      <button
        className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-colors ${
          totalValid
            ? 'bg-indigo-600 text-white hover:bg-indigo-700'
            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
        }`}
        disabled={!totalValid || publishMut.isPending}
        onClick={() => totalValid && publishMut.mutate(form)}
      >
        {publishMut.isPending ? 'Publishing…' : `Publish Ruleset ${form.version}`}
      </button>

      {/* Run Screening Now */}
      <div className="mt-8 bg-white rounded-lg border border-gray-200 shadow-sm p-5">
        <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">
          Entity Screening
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Screen all live-fund BLE counterparties and UBOs against OpenSanctions, and check
          document expiry dates. Results appear in the Suggested Reviews queue for analyst
          Accept / Decline.
        </p>
        <button
          className="w-full py-2.5 rounded-lg text-sm font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-gray-200 disabled:text-gray-400 transition-colors"
          disabled={screeningMut.isPending}
          onClick={() => {
            setScreeningResult(null)
            setScreeningError(null)
            screeningMut.mutate()
          }}
        >
          {screeningMut.isPending ? 'Screening entities…' : 'Run Screening Now'}
        </button>

        {screeningError && (
          <div className="mt-3 px-4 py-2.5 bg-red-50 border border-red-200 text-red-800 text-sm rounded-lg">
            Error: {screeningError}
          </div>
        )}

        {screeningResult && (
          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-gray-50 rounded-lg p-3 text-center">
                <div className="text-xl font-bold text-gray-900">{screeningResult.screened_entities}</div>
                <div className="text-xs text-gray-500 mt-0.5">Entities Screened</div>
              </div>
              <div className="bg-gray-50 rounded-lg p-3 text-center">
                <div className="text-xl font-bold text-amber-600">{screeningResult.triggers_fired}</div>
                <div className="text-xs text-gray-500 mt-0.5">Triggers Fired</div>
              </div>
              <div className="bg-gray-50 rounded-lg p-3 text-center">
                <div className="text-xl font-bold text-indigo-600">{screeningResult.cards_created}</div>
                <div className="text-xs text-gray-500 mt-0.5">Cards Created</div>
              </div>
            </div>

            <div className="border border-gray-100 rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500 uppercase">
                  <tr>
                    <th className="px-3 py-2 text-left">Entity</th>
                    <th className="px-3 py-2 text-left">Scope</th>
                    <th className="px-3 py-2 text-left">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {screeningResult.results.map((r, i) => (
                    <tr key={i}>
                      <td className="px-3 py-2 text-gray-700 font-medium">{r.name}</td>
                      <td className="px-3 py-2 text-gray-500">{r.scope}</td>
                      <td className="px-3 py-2">
                        {r.result === 'hit' ? (
                          <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs font-semibold uppercase">
                            {r.severity ?? 'hit'}
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs font-semibold uppercase">
                            clean
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {screeningResult.cards_created > 0 && (
              <button
                className="w-full py-2 rounded-lg text-sm font-medium border border-indigo-300 text-indigo-700 hover:bg-indigo-50 transition-colors"
                onClick={() => navigate('/suggested-reviews')}
              >
                View {screeningResult.cards_created} card{screeningResult.cards_created !== 1 ? 's' : ''} in Suggested Reviews →
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
