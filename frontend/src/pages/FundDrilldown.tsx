import { useState, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ExtractionResult, UploadedDoc } from '../api/client'
import { RiskBadge } from '../components/RiskBadge'
import { OpenSanctionsBadge } from '../components/OpenSanctionsBadge'
import { SyntheticBadge } from '../components/SyntheticBadge'
import { ScoreBar } from '../components/ScoreBar'
import { CitationChip } from '../components/CitationChip'

// Must match KNOWN_DOCUMENT_TYPES in services/extraction/service.py exactly
const DOC_TYPES = [
  'Incorporation Certificate',
  'UBO Declaration',
  'Counterparty Agreement',
  'Framework Agreement',
  'Annual Report',
  'Regulatory Licence',
  'Investment Manager Agreement',
]

function FieldsModal({
  result,
  onClose,
}: {
  result: ExtractionResult
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Extracted Fields</h2>
          <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs font-semibold rounded">
            Extracted
          </span>
        </div>
        <pre className="bg-gray-900 text-green-300 text-xs rounded-lg p-4 overflow-x-auto whitespace-pre-wrap break-words">
          {JSON.stringify(result.extracted_fields, null, 2)}
        </pre>
        <div className="mt-4 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export function FundDrilldown() {
  const { fundId } = useParams<{ fundId: string }>()
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const [showFactors, setShowFactors] = useState(false)

  // Upload modal state
  const [showUpload, setShowUpload] = useState(false)
  const [docType, setDocType] = useState(DOC_TYPES[0])
  const [expiry, setExpiry] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // Extraction state
  const [extractingId, setExtractingId] = useState<string | null>(null)
  const [extractionResults, setExtractionResults] = useState<Record<string, ExtractionResult>>({})
  const [viewFieldsDocId, setViewFieldsDocId] = useState<string | null>(null)

  const { data: fund, isLoading } = useQuery({
    queryKey: ['fund', fundId],
    queryFn: () => api.getFund(fundId!),
    enabled: !!fundId,
  })

  const { data: riskScore } = useQuery({
    queryKey: ['fund-risk', fundId],
    queryFn: () => api.getFundRiskScore(fundId!),
    enabled: !!fundId,
  })

  const { data: uploadedDocs = [], refetch: refetchUploaded } = useQuery<UploadedDoc[]>({
    queryKey: ['fund-uploaded-docs', fundId],
    queryFn: () => api.listFundUploadedDocs(fundId!),
    enabled: !!fundId && !fund?.synthetic_static,
  })

  const copilotMut = useMutation({
    mutationFn: (q: string) =>
      api.askCopilot({ question: q, fund_id: fundId, scope: 'fund', scope_id: fundId }),
  })

  const uploadMut = useMutation({
    mutationFn: () => {
      const file = fileRef.current?.files?.[0]
      if (!file) throw new Error('Please select a file')
      const fd = new FormData()
      fd.append('file', file)
      fd.append('document_type', docType)
      if (expiry) fd.append('expiry_date', expiry)
      return api.uploadFundDocument(fundId!, fd)
    },
    onSuccess: () => {
      refetchUploaded()
      setDocType(DOC_TYPES[0])
      setExpiry('')
      if (fileRef.current) fileRef.current.value = ''
    },
  })

  const extractMut = useMutation({
    mutationFn: (docId: string) => {
      setExtractingId(docId)
      return api.extractDocument(docId)
    },
    onSuccess: result => {
      setExtractionResults(prev => ({ ...prev, [result.document_id]: result }))
      setExtractingId(null)
    },
    onError: () => setExtractingId(null),
  })

  const closeUpload = () => {
    setShowUpload(false)
    uploadMut.reset()
    setDocType(DOC_TYPES[0])
    setExpiry('')
    if (fileRef.current) fileRef.current.value = ''
  }

  if (isLoading || !fund) {
    return <div className="p-8 text-gray-500">Loading fund…</div>
  }

  const isEscalated = fund.escalated_tier && fund.escalated_tier !== fund.direct_tier

  const viewingResult = viewFieldsDocId ? extractionResults[viewFieldsDocId] : null

  return (
    <div className="p-8 max-w-5xl">
      {/* Breadcrumb */}
      <div className="text-sm text-gray-400 mb-4">
        <button onClick={() => navigate('/')} className="hover:text-indigo-600 transition-colors">
          ← Command Centre
        </button>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold text-gray-900">{fund.name}</h1>
            <SyntheticBadge />
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {fund.incorporation_country} &middot; Ruleset {fund.ruleset_version}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <RiskBadge tier={fund.escalated_tier ?? fund.direct_tier} />
          <span className="text-xs text-gray-400">effective tier</span>
          {!fund.synthetic_static && (
            <Link
              to={`/reports/fund/${fundId}`}
              className="text-sm text-indigo-600 hover:underline font-medium mt-1"
            >
              View Analyst Report
            </Link>
          )}
        </div>
      </div>

      {/* Score line */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4 shadow-sm">
        <div className="flex items-center gap-6 flex-wrap">
          <div>
            <span className="text-xs text-gray-500 uppercase tracking-wide">Direct Score</span>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xl font-bold text-gray-900">{fund.direct_score}</span>
              <RiskBadge tier={fund.direct_tier} size="sm" />
            </div>
          </div>
          {isEscalated && (
            <>
              <div className="text-gray-300 text-xl">→</div>
              <div>
                <span className="text-xs text-gray-500 uppercase tracking-wide">Escalated To</span>
                <div className="flex items-center gap-2 mt-0.5">
                  <RiskBadge tier={fund.escalated_tier!} />
                  <span className="text-xs text-gray-500">(via BLE escalation)</span>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Escalation amber box */}
      {isEscalated && (
        <div className="bg-amber-50 border border-amber-300 rounded-lg p-4 mb-4 text-sm">
          <div className="font-semibold text-amber-800 mb-1">BLE Escalation — Fund surfaced as Critical</div>
          <p className="text-amber-700">{fund.escalation_reason}</p>
          {fund.bles.filter(b => b.tier === 'critical').map(b => (
            <div key={b.ble_id} className="mt-2 flex items-center gap-2">
              <span className="text-amber-700 font-medium">↑ Critical BLE:</span>
              <Link
                to={`/bles/${b.ble_id}`}
                className="text-indigo-700 font-semibold hover:underline"
                onClick={e => e.stopPropagation()}
              >
                {b.name}
              </Link>
              <OpenSanctionsBadge show={b.screening_is_real} />
            </div>
          ))}
        </div>
      )}

      {/* Static fund banner */}
      {fund.synthetic_static && (
        <div className="bg-gray-100 border border-gray-300 rounded-lg p-4 mb-4 text-sm text-gray-600">
          Static demo fund — no AI pipeline (RAG, LLM calls, and extraction are disabled for this fund).
        </div>
      )}

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* BLE table */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="px-4 py-3 border-b border-gray-100 font-semibold text-gray-800 text-sm">
            BLEs ({fund.bles.length})
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-4 py-2 text-left">BLE</th>
                <th className="px-4 py-2 text-left">Tier</th>
                <th className="px-4 py-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {fund.bles.map(ble => (
                <tr
                  key={ble.ble_id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/bles/${ble.ble_id}`)}
                >
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1 flex-wrap">
                      <span className="text-gray-800">{ble.name}</span>
                      <OpenSanctionsBadge show={ble.screening_is_real} />
                    </div>
                  </td>
                  <td className="px-4 py-2"><RiskBadge tier={ble.tier} size="sm" /></td>
                  <td className="px-4 py-2 text-right font-mono text-gray-600">{ble.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Seeded documents table */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="px-4 py-3 border-b border-gray-100 font-semibold text-gray-800 text-sm">
            Fund Documents (on-file)
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Expiry</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {fund.documents.map(doc => {
                const expired = doc.expiry_date && doc.expiry_date < '2026-06-20'
                return (
                  <tr key={doc.doc_id}>
                    <td className="px-4 py-2 text-gray-700">{doc.document_type.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                        doc.status === 'active' ? 'bg-green-100 text-green-700' :
                        doc.status === 'expired' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-600'
                      }`}>{doc.status}</span>
                    </td>
                    <td className={`px-4 py-2 text-xs ${expired ? 'text-red-600 font-semibold' : 'text-gray-500'}`}>
                      {doc.expiry_date ?? '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pipeline documents (uploaded via this session) */}
      {!fund.synthetic_static && (
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <span className="font-semibold text-gray-800 text-sm">
              Uploaded Documents (Pipeline)
              {uploadedDocs.length > 0 && (
                <span className="ml-2 text-xs text-gray-400">({uploadedDocs.length})</span>
              )}
            </span>
            <button
              onClick={() => setShowUpload(true)}
              className="text-xs px-2.5 py-1 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 transition-colors"
            >
              + Upload
            </button>
          </div>
          {uploadedDocs.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-gray-400 italic">
              No documents uploaded yet — click Upload to add one.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                <tr>
                  <th className="px-4 py-2 text-left">Type</th>
                  <th className="px-4 py-2 text-left">File</th>
                  <th className="px-4 py-2 text-left">Extraction</th>
                  <th className="px-4 py-2 text-left">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {uploadedDocs.map(doc => {
                  const isExtracting = extractingId === doc.document_id
                  const result = extractionResults[doc.document_id]
                  const isExtracted = result != null || doc.extraction_status === 'extracted'
                  return (
                    <tr key={doc.document_id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-800 font-medium">{doc.document_type}</td>
                      <td className="px-4 py-2 text-xs text-gray-500 font-mono">{doc.filename ?? '—'}</td>
                      <td className="px-4 py-2">
                        {isExtracted ? (
                          <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                            extracted
                          </span>
                        ) : doc.extraction_status === 'failed' ? (
                          <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                            failed
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-700">
                            pending
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        {isExtracted && result ? (
                          <button
                            onClick={() => setViewFieldsDocId(doc.document_id)}
                            className="text-xs px-2.5 py-1 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
                          >
                            View Fields
                          </button>
                        ) : isExtracting ? (
                          <span className="text-xs text-indigo-500 animate-pulse">Extracting…</span>
                        ) : (
                          <button
                            onClick={() => extractMut.mutate(doc.document_id)}
                            className="text-xs px-2.5 py-1 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 transition-colors"
                          >
                            Extract
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Risk factor breakdown toggle */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
        <button
          className="w-full px-5 py-3 flex items-center justify-between text-sm font-semibold text-gray-700 hover:bg-gray-50 transition-colors"
          onClick={() => setShowFactors(v => !v)}
        >
          <span>Risk Factor Breakdown</span>
          <span>{showFactors ? '▲' : '▼'}</span>
        </button>
        {showFactors && riskScore && (
          <div className="px-5 pb-5 pt-2">
            <ScoreBar factorScores={riskScore.factor_scores} />
          </div>
        )}
      </div>

      {/* RAG / Ask panel — hidden for static funds */}
      {!fund.synthetic_static && (
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5">
          <h3 className="font-semibold text-gray-800 mb-3">Ask about this Fund (scoped RAG)</h3>
          <div className="flex gap-2 mb-4">
            <input
              className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              placeholder="e.g. What are the UBO risk factors?"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && question.trim()) copilotMut.mutate(question) }}
            />
            <button
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              disabled={!question.trim() || copilotMut.isPending}
              onClick={() => copilotMut.mutate(question)}
            >
              {copilotMut.isPending ? '…' : 'Ask'}
            </button>
          </div>
          {copilotMut.data && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                  copilotMut.data.routing === 'text-to-sql'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-purple-100 text-purple-700'
                }`}>
                  {copilotMut.data.routing}
                </span>
                {copilotMut.data.is_mock && (
                  <span className="text-xs text-gray-400">MOCK</span>
                )}
              </div>
              <p className="text-sm text-gray-800 whitespace-pre-wrap">{copilotMut.data.answer}</p>
              {copilotMut.data.sql && (
                <pre className="bg-gray-900 text-green-300 text-xs rounded p-3 overflow-x-auto">
                  {copilotMut.data.sql}
                </pre>
              )}
              {copilotMut.data.citations.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {copilotMut.data.citations.map((c, i) => (
                    <CitationChip key={i} text={c.text} docType={c.document_type} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Upload Document modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={closeUpload}>
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Upload Fund Document</h2>
            {uploadMut.isSuccess ? (
              <div className="space-y-4">
                <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm">
                  <div className="font-semibold text-green-800 mb-1">Upload successful</div>
                  <div className="text-green-700">Document registered — click Extract to run Haiku extraction.</div>
                  <div className="text-xs text-green-600 mt-2 font-mono break-all">
                    ID: {uploadMut.data?.document_id}
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => uploadMut.reset()} className="px-3 py-2 text-sm text-indigo-600 hover:underline">
                    Upload another
                  </button>
                  <button onClick={closeUpload} className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700">
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-600 mb-1">Document Type</label>
                  <select
                    value={docType}
                    onChange={e => setDocType(e.target.value)}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  >
                    {DOC_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">
                    File <span className="text-gray-400">(.txt for demo)</span>
                  </label>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".txt,.pdf"
                    className="w-full text-sm text-gray-700 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">
                    Expiry Date <span className="text-gray-400">(optional)</span>
                  </label>
                  <input
                    type="date"
                    value={expiry}
                    onChange={e => setExpiry(e.target.value)}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                </div>
                {uploadMut.isError && (
                  <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">
                    {String(uploadMut.error)}
                  </div>
                )}
                <div className="flex justify-end gap-2 pt-1">
                  <button onClick={closeUpload} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
                    Cancel
                  </button>
                  <button
                    onClick={() => uploadMut.mutate()}
                    disabled={uploadMut.isPending}
                    className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {uploadMut.isPending ? 'Uploading…' : 'Upload'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Extracted fields viewer modal */}
      {viewingResult && (
        <FieldsModal result={viewingResult} onClose={() => setViewFieldsDocId(null)} />
      )}
    </div>
  )
}
