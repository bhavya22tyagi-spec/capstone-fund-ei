import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { EvalRunSummary } from '../types'

const STATUS_STYLE: Record<string, string> = {
  pass:    'bg-green-100 text-green-700',
  fail:    'bg-red-100 text-red-700',
  pending: 'bg-gray-100 text-gray-500',
  running: 'bg-blue-100 text-blue-700',
}

const CATEGORY_LABELS: Record<string, string> = {
  A: 'Extraction Accuracy',
  B: 'Embedding Quality',
  C: 'RAG Groundedness',
  D: 'Text-to-SQL Accuracy',
  E: 'Escalation Cascade',
  F: 'Copilot Guardrails',
  G: 'End-to-End (E2E)',
}

function PassBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
        <div
          className={`h-full rounded-full ${pct >= 90 ? 'bg-green-500' : pct >= 70 ? 'bg-yellow-400' : 'bg-red-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono w-10 text-right text-gray-700">{pct}%</span>
    </div>
  )
}

export function EvalDashboard() {
  const { data: evals = [], isLoading } = useQuery({
    queryKey: ['evals'],
    queryFn: api.getEvals,
  })

  if (isLoading) return <div className="p-8 text-gray-500">Loading eval dashboard…</div>

  const total = evals.length
  const passing = evals.filter((e: EvalRunSummary) => e.status === 'pass').length
  const totalCost = evals.reduce((s: number, e: EvalRunSummary) => s + (e.cost_usd ?? 0), 0)
  const avgLatency = evals.filter((e: EvalRunSummary) => e.latency_ms > 0).reduce(
    (s: number, e: EvalRunSummary, _: number, arr: EvalRunSummary[]) => s + e.latency_ms / arr.length,
    0,
  )

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Eval / Guardrail Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Golden-dataset evaluations across all AI surfaces — PRD §15.2
        </p>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
          <div className="text-2xl font-bold text-gray-900">{passing}/{total}</div>
          <div className="text-sm text-gray-500 mt-0.5">Categories Passing</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
          <div className="text-2xl font-bold text-gray-900">
            {evals.length > 0
              ? `${Math.round(evals.filter((e: EvalRunSummary) => e.pass_rate > 0).reduce((s: number, e: EvalRunSummary, _: number, a: EvalRunSummary[]) => s + e.pass_rate / a.length, 0) * 100)}%`
              : '—'}
          </div>
          <div className="text-sm text-gray-500 mt-0.5">Avg Pass Rate</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
          <div className="text-2xl font-bold text-gray-900">
            {avgLatency > 0 ? `${Math.round(avgLatency)}ms` : '—'}
          </div>
          <div className="text-sm text-gray-500 mt-0.5">Avg Latency</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
          <div className="text-2xl font-bold text-gray-900">
            ${totalCost > 0 ? totalCost.toFixed(4) : '0.0000'}
          </div>
          <div className="text-sm text-gray-500 mt-0.5">Total Cost (MOCK)</div>
        </div>
      </div>

      {/* Eval table */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-5 py-3 text-left w-8">Cat.</th>
              <th className="px-5 py-3 text-left">Label</th>
              <th className="px-5 py-3 text-left">Pass Rate</th>
              <th className="px-5 py-3 text-right">Pass</th>
              <th className="px-5 py-3 text-right">Fail</th>
              <th className="px-5 py-3 text-right">Latency</th>
              <th className="px-5 py-3 text-right">Cost</th>
              <th className="px-5 py-3 text-left">Status</th>
              <th className="px-5 py-3 text-left">Last Run</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {evals.map((e: EvalRunSummary) => (
              <tr key={e.eval_category} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-bold text-gray-600">{e.eval_category}</td>
                <td className="px-5 py-3 text-gray-800">
                  <div>{CATEGORY_LABELS[e.eval_category] ?? e.label}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{e.label}</div>
                </td>
                <td className="px-5 py-3 w-40">
                  {e.status === 'pending' ? (
                    <span className="text-xs text-gray-400 italic">not run</span>
                  ) : (
                    <PassBar rate={e.pass_rate} />
                  )}
                </td>
                <td className="px-5 py-3 text-right font-mono text-green-700">{e.pass_count || '—'}</td>
                <td className="px-5 py-3 text-right font-mono text-red-600">{e.fail_count || '—'}</td>
                <td className="px-5 py-3 text-right font-mono text-gray-600">
                  {e.latency_ms ? `${e.latency_ms}ms` : '—'}
                </td>
                <td className="px-5 py-3 text-right font-mono text-gray-600">
                  {e.cost_usd ? `$${e.cost_usd.toFixed(4)}` : '—'}
                </td>
                <td className="px-5 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${STATUS_STYLE[e.status] ?? STATUS_STYLE.pending}`}>
                    {e.status.toUpperCase()}
                  </span>
                  {e.is_mock && <span className="ml-1.5 text-xs text-gray-400">MOCK</span>}
                </td>
                <td className="px-5 py-3 text-xs text-gray-400">
                  {e.last_run_at ? new Date(e.last_run_at).toLocaleString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 text-xs text-gray-400">
        All eval runs use MOCK=true — no real API credits consumed. To run live evals, set MOCK=false and use <code>uv run pytest evals/</code>.
      </div>
    </div>
  )
}
