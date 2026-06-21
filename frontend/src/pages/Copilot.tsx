import { useState, useCallback, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { CitationChip } from '../components/CitationChip'

const EXAMPLE_QUERIES = [
  'Which funds have a Critical BLE under them?',
  'What changed in Bank Rossiya\'s screening status?',
  'List all funds with expired documents',
  'How many BLEs have an active sanctions hit?',
]

interface StreamMeta {
  routing: string
  sql: string | null
  citations: Array<{ text: string; doc_id: string; document_type: string }>
  is_mock: boolean
}

export function Copilot() {
  const [question, setQuestion] = useState('')
  const [fundId, setFundId] = useState('')
  const [streamedText, setStreamedText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamMeta, setStreamMeta] = useState<StreamMeta | null>(null)
  const [askedQuestion, setAskedQuestion] = useState('')
  const [error, setError] = useState<string | null>(null)
  const accRef = useRef('')

  const { data: funds = [] } = useQuery({
    queryKey: ['funds'],
    queryFn: api.getFunds,
  })
  const liveFunds = funds.filter((f: { synthetic_static: boolean }) => !f.synthetic_static)

  const ask = useCallback(async (q: string) => {
    setAskedQuestion(q)
    setStreamedText('')
    accRef.current = ''
    setStreamMeta(null)
    setError(null)
    setIsStreaming(true)

    const params = new URLSearchParams({ question: q })
    if (fundId) {
      params.set('fund_id', fundId)
      params.set('scope', 'fund')
      params.set('scope_id', fundId)
    }

    try {
      const resp = await fetch(`/api/copilot/stream?${params.toString()}`)
      if (!resp.ok || !resp.body) {
        setError(`Request failed: ${resp.status}`)
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const chunks = buf.split('\n\n')
        buf = chunks.pop() ?? ''

        for (const chunk of chunks) {
          const line = chunk.startsWith('data: ') ? chunk.slice(6) : chunk
          if (!line.trim()) continue
          try {
            const msg: Record<string, unknown> = JSON.parse(line)
            if (typeof msg.token === 'string' && !msg.done) {
              accRef.current += msg.token
              setStreamedText(accRef.current)
            }
            if (msg.done) {
              if (typeof msg.token === 'string' && msg.token) {
                accRef.current += msg.token
                setStreamedText(accRef.current)
              }
              setStreamMeta({
                routing: String(msg.routing ?? 'rag'),
                sql: msg.sql != null ? String(msg.sql) : null,
                citations: Array.isArray(msg.citations) ? msg.citations as StreamMeta['citations'] : [],
                is_mock: Boolean(msg.is_mock),
              })
            }
          } catch {
            // skip malformed SSE chunk
          }
        }
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setIsStreaming(false)
    }
  }, [fundId])

  const handleAsk = () => {
    if (question.trim()) ask(question)
  }

  const hasResult = streamMeta !== null
  const isActive = isStreaming || hasResult

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Copilot / Ask</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          RAG + Text-to-SQL hybrid · streaming · all queries scoped — no cross-fund leakage.
        </p>
      </div>

      {/* Context selector */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4 mb-4">
        <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">
          Fund Context (optional — limits scope)
        </label>
        <select
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          value={fundId}
          onChange={e => setFundId(e.target.value)}
        >
          <option value="">All Funds (portfolio-level)</option>
          {liveFunds.map((f: { fund_id: string; name: string }) => (
            <option key={f.fund_id} value={f.fund_id}>{f.name}</option>
          ))}
        </select>
      </div>

      {/* Query input */}
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4 mb-4">
        <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1.5">
          Your Question
        </label>
        <textarea
          rows={3}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
          placeholder="Ask anything about compliance, risk, or screening…"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && question.trim()) {
              e.preventDefault()
              handleAsk()
            }
          }}
        />
        <div className="flex justify-end mt-2">
          <button
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            disabled={!question.trim() || isStreaming}
            onClick={handleAsk}
          >
            {isStreaming ? 'Thinking…' : 'Ask'}
          </button>
        </div>
      </div>

      {/* Example chips */}
      <div className="mb-6">
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">Try an example</div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUERIES.map(q => (
            <button
              key={q}
              className="px-3 py-1.5 text-xs border border-indigo-200 text-indigo-700 rounded-full hover:bg-indigo-50 transition-colors disabled:opacity-40"
              disabled={isStreaming}
              onClick={() => { setQuestion(q); ask(q) }}
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Streaming / answer panel */}
      {isActive && (
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5 space-y-4">
          {/* Routing badge (shown once meta arrives) */}
          {streamMeta && (
            <div className="flex items-center gap-2">
              <span className={`px-2.5 py-1 rounded text-xs font-semibold ${
                streamMeta.routing === 'text-to-sql'
                  ? 'bg-blue-100 text-blue-700'
                  : streamMeta.routing === 'hybrid'
                  ? 'bg-teal-100 text-teal-700'
                  : 'bg-purple-100 text-purple-700'
              }`}>
                {streamMeta.routing === 'text-to-sql' ? '🗄️ Text-to-SQL'
                  : streamMeta.routing === 'hybrid' ? '⚡ Hybrid'
                  : '📄 RAG'}
              </span>
              {streamMeta.is_mock && (
                <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">MOCK</span>
              )}
            </div>
          )}

          {/* Question echo */}
          <div className="text-xs text-gray-400 italic">"{askedQuestion}"</div>

          {/* Streamed answer text */}
          <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
            {streamedText}
            {isStreaming && (
              <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-indigo-500 animate-pulse rounded-sm align-text-bottom" />
            )}
          </p>

          {/* SQL block (after done) */}
          {streamMeta?.sql && (
            <div>
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Generated SQL
              </div>
              <pre className="bg-gray-900 text-green-300 text-xs rounded-lg p-4 overflow-x-auto leading-relaxed">
                {streamMeta.sql}
              </pre>
            </div>
          )}

          {/* Citations (after done) */}
          {streamMeta && streamMeta.citations.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Source Citations
              </div>
              <div className="flex flex-col gap-2">
                {streamMeta.citations.map((c, i) => (
                  <CitationChip key={i} text={c.text} docType={c.document_type} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Error: {error}
        </div>
      )}
    </div>
  )
}
