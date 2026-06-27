import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { RiskBadge } from '../components/RiskBadge'
import { OpenSanctionsBadge } from '../components/OpenSanctionsBadge'
import { ScoreBar } from '../components/ScoreBar'
import { CitationChip } from '../components/CitationChip'
import type { RiskTier } from '../types'

type Decision = 'none' | 'accepted' | 'rejected'

export function AnalystReport() {
  const { scope, scopeId } = useParams<{ scope: string; scopeId: string }>()
  const [decision, setDecision] = useState<Decision>('none')
  const [editing, setEditing] = useState(false)
  const [editedNarrative, setEditedNarrative] = useState('')

  const { data: report, isLoading, error } = useQuery({
    queryKey: ['report', scope, scopeId],
    queryFn: () => api.getAnalystReport(scope!, scopeId!),
    enabled: !!(scope && scopeId),
  })

  const decisionMut = useMutation({
    mutationFn: (body: { decision: 'accepted' | 'rejected' | 'edited'; notes?: string; edited_narrative?: string }) =>
      api.submitDecision(scope!, scopeId!, { actor: 'analyst', ...body }),
  })

  if (isLoading) {
    return <div className="p-8 text-gray-500">Generating analyst report…</div>
  }
  if (error || !report) {
    const msg = error instanceof Error ? error.message : 'Unknown error'
    return <div className="p-8 text-red-600">Failed to load report: {msg}</div>
  }

  const backPath =
    scope === 'fund' ? `/funds/${scopeId}` : `/bles/${scopeId}`
  const backLabel =
    scope === 'fund' ? '← Fund Drilldown' : '← BLE Drilldown'
  const entityName = report.ble_name ?? report.fund_name

  const narrativeText = editing ? editedNarrative : report.narrative

  function handleAccept() {
    setDecision('accepted')
    decisionMut.mutate({ decision: 'accepted' })
  }

  function handleReject() {
    setDecision('rejected')
    decisionMut.mutate({ decision: 'rejected' })
  }

  function handleSaveEdits() {
    setEditing(false)
    decisionMut.mutate({ decision: 'edited', edited_narrative: editedNarrative })
  }

  return (
    <div className="p-8 max-w-4xl space-y-6">

      {/* ── Header ── */}
      <div>
        <div className="text-sm text-gray-400 mb-3">
          <Link to={backPath} className="hover:text-indigo-600 transition-colors">
            {backLabel}
          </Link>
        </div>
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold text-gray-900">{entityName}</h1>
              <RiskBadge tier={report.effective_tier as RiskTier} />
              {report.is_mock && (
                <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded font-medium">
                  MOCK
                </span>
              )}
            </div>
            <p className="text-sm text-gray-500 mt-1">
              Scope: <span className="capitalize font-medium">{report.scope}</span>
              &nbsp;&middot;&nbsp;Ruleset {report.ruleset_version}
              &nbsp;&middot;&nbsp;{new Date(report.generated_at).toLocaleDateString()}
            </p>
          </div>
          <div className="text-right text-sm text-gray-500">
            <div>Direct tier: <span className="font-medium capitalize">{report.direct_tier}</span></div>
            <div>Score: <span className="font-medium">{report.direct_score.toFixed(1)}</span></div>
          </div>
        </div>
      </div>

      {/* ── Escalation Context (Fund scope only) ── */}
      {report.scope === 'fund' && report.escalation_reason && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-1">Escalation Context</h3>
          <p className="text-sm text-amber-700">{report.escalation_reason}</p>
          {report.escalated_ble_names.length > 0 && (
            <p className="text-sm text-amber-700 mt-1">
              Escalating BLEs: <span className="font-medium">{report.escalated_ble_names.join(', ')}</span>
            </p>
          )}
        </div>
      )}

      {/* ── Executive Summary ── */}
      <section className="bg-white border border-gray-200 rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-900">Executive Summary</h2>
          {!editing && decision === 'none' && (
            <button
              onClick={() => { setEditing(true); setEditedNarrative(report.narrative) }}
              className="text-xs text-indigo-600 hover:underline"
            >
              Edit narrative
            </button>
          )}
        </div>
        {editing ? (
          <div className="space-y-2">
            <textarea
              value={editedNarrative}
              onChange={e => setEditedNarrative(e.target.value)}
              rows={10}
              className="w-full text-sm border border-gray-300 rounded p-2 font-mono focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
            <button
              onClick={() => setEditing(false)}
              className="text-xs text-gray-500 hover:text-gray-700 mr-3"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveEdits}
              className="text-xs bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700"
            >
              Save edits
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
            {narrativeText}
          </p>
        )}
        {report.citations.length > 0 && !editing && (
          <div className="mt-3 flex flex-wrap gap-2">
            {report.citations.map((c, i) => (
              <CitationChip
                key={i}
                text={c.citation_text.slice(0, 80) + (c.citation_text.length > 80 ? '…' : '')}
                docType={c.document_type}
              />
            ))}
          </div>
        )}
      </section>

      {/* ── Risk Factor Breakdown ── */}
      {Object.keys(report.factor_scores).length > 0 && (
        <section className="bg-white border border-gray-200 rounded-lg p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-3">Risk Factor Breakdown</h2>
          <ScoreBar factorScores={report.factor_scores} />
        </section>
      )}

      {/* ── Screening / Adverse Media ── */}
      <section className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Screening &amp; Adverse Media</h2>
        {report.screening_status || report.hit_type ? (
          <div className="flex items-center gap-3">
            <OpenSanctionsBadge show={true} />
            <div className="text-sm">
              <span className="text-red-700 font-medium capitalize">{report.hit_type ?? 'Hit'}</span>
              {report.screening_status && (
                <span className="text-gray-500 ml-2">· {report.screening_status}</span>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm text-green-700 font-medium">Clean — no sanctions or PEP hits</p>
        )}
      </section>

      {/* ── Document Status ── */}
      <section className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Document Status</h2>
        {report.document_status.length === 0 ? (
          <p className="text-sm text-gray-400">No documents on record.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100">
                <th className="pb-2 font-medium">Type</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Expiry</th>
              </tr>
            </thead>
            <tbody>
              {report.document_status.map(doc => (
                <tr key={doc.doc_id} className="border-b border-gray-50">
                  <td className="py-2 text-gray-700">{doc.document_type}</td>
                  <td className="py-2 capitalize text-gray-600">{doc.status}</td>
                  <td className="py-2 text-gray-500">{doc.expiry_date ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Recommended Action (HITL) ── */}
      <section className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-1">Recommended Action</h2>
        <p className="text-xs text-gray-400 mb-3">
          AI-suggested · PRD §18: no AI output auto-publishes · decisions logged for audit
        </p>
        {decision === 'none' ? (
          <div className="flex gap-3">
            <button
              onClick={handleAccept}
              disabled={decisionMut.isPending}
              className="px-4 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 font-medium disabled:opacity-50"
            >
              Accept
            </button>
            <button
              onClick={() => { setEditing(true); setEditedNarrative(report.narrative) }}
              disabled={decisionMut.isPending}
              className="px-4 py-1.5 text-sm border border-gray-300 text-gray-700 rounded hover:bg-gray-50 font-medium disabled:opacity-50"
            >
              Edit
            </button>
            <button
              onClick={handleReject}
              disabled={decisionMut.isPending}
              className="px-4 py-1.5 text-sm bg-red-50 text-red-700 border border-red-200 rounded hover:bg-red-100 font-medium disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        ) : decision === 'accepted' ? (
          <div>
            <p className="text-sm text-green-700 font-medium">Report accepted.</p>
            {decisionMut.isSuccess && (
              <p className="text-xs text-gray-400 mt-1">
                Decision logged · {decisionMut.data?.decided_at}
              </p>
            )}
          </div>
        ) : (
          <div>
            <p className="text-sm text-red-700 font-medium">Report rejected. No action will be taken.</p>
            {decisionMut.isSuccess && (
              <p className="text-xs text-gray-400 mt-1">
                Decision logged · {decisionMut.data?.decided_at}
              </p>
            )}
          </div>
        )}
      </section>

      {/* ── Audit Footer ── */}
      <section className="border-t border-gray-100 pt-4 text-xs text-gray-400 space-y-0.5">
        <div>Model: <span className="text-gray-600">{report.model}</span></div>
        <div>Prompt version: <span className="text-gray-600">{report.prompt_version}</span></div>
        <div>Citations: <span className="text-gray-600">{report.citations.length}</span></div>
        <div>Generated: <span className="text-gray-600">{report.generated_at}</span></div>
        <div>Mock: <span className="text-gray-600">{String(report.is_mock)}</span></div>
      </section>

    </div>
  )
}
