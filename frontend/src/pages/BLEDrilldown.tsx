import { useState, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ExtractionResult, UploadedDoc, ScreeningResult } from '../api/client'
import { RiskBadge } from '../components/RiskBadge'
import { OpenSanctionsBadge } from '../components/OpenSanctionsBadge'
import { SyntheticBadge } from '../components/SyntheticBadge'
import { ScoreBar } from '../components/ScoreBar'

const STATUS_STYLE: Record<string, string> = {
  clear:    'bg-green-100 text-green-700',
  hit:      'bg-red-100 text-red-700',
  pep:      'bg-purple-100 text-purple-700',
  pending:  'bg-yellow-100 text-yellow-700',
  unknown:  'bg-gray-100 text-gray-600',
}

// Must match KNOWN_DOCUMENT_TYPES in services/extraction/service.py exactly
const DOC_TYPES = [
  'Counterparty Agreement',
  'Framework Agreement',
  'Regulatory Licence',
  'Annual Report',
  'Incorporation Certificate',
  'UBO Declaration',
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

export function BLEDrilldown() {
  const { bleId } = useParams<{ bleId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [showFactors, setShowFactors] = useState(false)
  const [screeningError, setScreeningError] = useState<string | null>(null)

  // Upload modal state
  const [showUpload, setShowUpload] = useState(false)
  const [docType, setDocType] = useState(DOC_TYPES[0])
  const [expiry, setExpiry] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // Extraction state
  const [extractingId, setExtractingId] = useState<string | null>(null)
  const [extractionResults, setExtractionResults] = useState<Record<string, ExtractionResult>>({})
  const [viewFieldsDocId, setViewFieldsDocId] = useState<string | null>(null)

  const { data: ble, isLoading } = useQuery({
    queryKey: ['ble', bleId],
    queryFn: () => api.getBLE(bleId!),
    enabled: !!bleId,
  })

  const { data: riskScore } = useQuery({
    queryKey: ['ble-risk', bleId],
    queryFn: () => api.getBLERiskScore(bleId!),
    enabled: !!bleId,
  })

  const { data: uploadedDocs = [], refetch: refetchUploaded } = useQuery<UploadedDoc[]>({
    queryKey: ['ble-uploaded-docs', bleId],
    queryFn: () => api.listBLEUploadedDocs(bleId!),
    enabled: !!bleId,
  })

  const uploadMut = useMutation({
    mutationFn: () => {
      const file = fileRef.current?.files?.[0]
      if (!file) throw new Error('Please select a file')
      const fd = new FormData()
      fd.append('file', file)
      fd.append('document_type', docType)
      if (expiry) fd.append('expiry_date', expiry)
      return api.uploadBLEDocument(bleId!, fd)
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

  const { data: screeningResult } = useQuery({
    queryKey: ['ble-last-screening', bleId],
    queryFn: () => api.getLastScreening(bleId!),
    enabled: !!bleId,
  })

  const screenMut = useMutation({
    mutationFn: () => api.screenSingleBle(bleId!),
    onSuccess: (data) => {
      qc.setQueryData(['ble-last-screening', bleId], data)
      setScreeningError(null)
    },
    onError: (err: Error) => setScreeningError(err.message),
  })

  const closeUpload = () => {
    setShowUpload(false)
    uploadMut.reset()
    setDocType(DOC_TYPES[0])
    setExpiry('')
    if (fileRef.current) fileRef.current.value = ''
  }

  if (isLoading || !ble) {
    return <div className="p-8 text-gray-500">Loading BLE…</div>
  }

  const statusKey = ble.hit_type ?? ble.screening_status ?? 'unknown'
  const normalizedStatus = statusKey.toLowerCase().includes('clear') ? 'clear'
    : statusKey.toLowerCase().includes('hit') || statusKey.toLowerCase().includes('sanction') ? 'hit'
    : statusKey.toLowerCase().includes('pep') ? 'pep'
    : statusKey

  const viewingResult = viewFieldsDocId ? extractionResults[viewFieldsDocId] : null

  return (
    <div className="p-8 max-w-4xl">
      {/* Breadcrumb */}
      <div className="text-sm text-gray-400 mb-4">
        <button
          onClick={() => navigate(`/funds/${ble.fund_id}`)}
          className="hover:text-indigo-600 transition-colors"
        >
          ← Back to {ble.fund_name}
        </button>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold text-gray-900">{ble.name}</h1>
            <OpenSanctionsBadge show={ble.screening_is_real} />
            <SyntheticBadge />
          </div>
          <div className="text-sm text-gray-500 mt-1">
            BLE of <span className="font-medium text-gray-700">{ble.fund_name}</span>
            &middot; Ruleset {ble.ruleset_version}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <RiskBadge tier={ble.tier} />
          <span className="text-xs text-gray-400">BLE score: {ble.score}</span>
          <Link
            to={`/reports/ble/${bleId}`}
            className="text-sm text-indigo-600 hover:underline font-medium mt-1"
          >
            View Analyst Report
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Counterparty Profile */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5">
          <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
            Counterparty Profile
          </h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500">Institution</dt>
              <dd className="font-medium text-gray-800">{ble.institution}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Location</dt>
              <dd className="font-medium text-gray-800">{ble.location}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Country</dt>
              <dd className="font-medium text-gray-800">{ble.counterparty_country}</dd>
            </div>
            <div className="flex justify-between items-center">
              <dt className="text-gray-500">Screening Status</dt>
              <dd>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${STATUS_STYLE[normalizedStatus] ?? STATUS_STYLE.unknown}`}>
                  {ble.screening_status}
                </span>
              </dd>
            </div>
            {ble.hit_type && (
              <div className="flex justify-between">
                <dt className="text-gray-500">Hit Type</dt>
                <dd className="text-red-700 font-semibold">{ble.hit_type}</dd>
              </div>
            )}
            {ble.hit_severity && (
              <div className="flex justify-between">
                <dt className="text-gray-500">Severity</dt>
                <dd className="text-red-700 font-semibold">{ble.hit_severity}</dd>
              </div>
            )}
          </dl>
          {ble.screening_is_real && (
            <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-blue-700 flex items-center gap-1.5">
              <span>🔍</span>
              Live result from OpenSanctions — not synthetic
            </div>
          )}

          <div className="mt-3 pt-3 border-t border-gray-100">
              <button
                className="w-full py-2 rounded-lg text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-gray-200 disabled:text-gray-400 transition-colors"
                disabled={screenMut.isPending}
                onClick={() => { setScreeningResult(null); setScreeningError(null); screenMut.mutate() }}
              >
                {screenMut.isPending ? 'Screening…' : 'Screen this counterparty'}
              </button>

              {screeningError && (
                <p className="mt-2 text-xs text-red-600">{screeningError}</p>
              )}

              {screeningResult && (
                <div className="mt-2 space-y-2 text-sm">
                  {screeningResult.results.map((r, i) => (
                    <div key={i}>
                      <div className="flex justify-between items-center">
                        <span className="text-gray-600">{r.name}</span>
                        {r.result === 'hit' ? (
                          <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs font-semibold uppercase">
                            {r.severity ?? 'hit'}
                          </span>
                        ) : r.result === 'error' ? (
                          <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-semibold uppercase">
                            ⚠ api error
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-semibold uppercase">
                            clean
                          </span>
                        )}
                      </div>
                      {r.result === 'hit' && (r.hit_type || r.datasets.length > 0 || r.screened_at) && (
                        <div className="mt-1 text-xs text-gray-500 space-y-0.5 pl-0.5">
                          {r.hit_type && (
                            <div>
                              <span className="font-medium text-red-600">
                                {r.hit_type === 'sanctions' ? 'Sanctions' : r.hit_type === 'pep' ? 'PEP' : 'Adverse Media'}
                              </span>
                            </div>
                          )}
                          {r.datasets.length > 0 && (
                            <div className="text-gray-400">
                              {r.datasets.map(d =>
                                d.replace('us_ofac_sdn', 'OFAC SDN')
                                 .replace('eu_sanctions', 'EU Sanctions')
                                 .replace(/_/g, ' ')
                                 .replace(/\b\w/g, c => c.toUpperCase())
                              ).join(' · ')}
                            </div>
                          )}
                          {r.screened_at && (
                            <div className="text-gray-500 font-semibold">
                              Screened {new Date(r.screened_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
          </div>
        </div>

        {/* Products */}
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
          <div className="px-4 py-3 border-b border-gray-100 font-semibold text-gray-800 text-sm">
            Products ({ble.products.length})
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Workflow</th>
                <th className="px-4 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {ble.products.map(p => (
                <tr key={p.product_id}>
                  <td className="px-4 py-2 font-medium text-gray-800">{p.product_type}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{p.workflow_template}</td>
                  <td className="px-4 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                      p.status === 'active' ? 'bg-green-100 text-green-700' :
                      p.status === 'pending_review' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>{p.status.replace(/_/g, ' ')}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* BLE Documents (on-file / seeded) */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm mb-6">
        <div className="px-4 py-3 border-b border-gray-100 font-semibold text-gray-800 text-sm">
          BLE Documents (on-file)
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Type</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Expiry</th>
              <th className="px-4 py-2 text-left">Extraction</th>
              <th className="px-4 py-2 text-left">Embedding</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {ble.documents.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-center text-gray-400 italic">
                  No documents on file
                </td>
              </tr>
            ) : ble.documents.map(doc => {
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
                  <td className="px-4 py-2 text-xs text-gray-500">{doc.extraction_status}</td>
                  <td className="px-4 py-2 text-xs text-gray-500">{doc.embedding_status}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pipeline documents (uploaded) */}
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

      {/* Risk factor breakdown */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
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

      {/* Upload Document modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={closeUpload}>
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Upload BLE Document</h2>
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
