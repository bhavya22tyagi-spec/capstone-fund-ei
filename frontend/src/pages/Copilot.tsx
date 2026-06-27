export function Copilot() {
  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Copilot / Ask</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          RAG + Text-to-SQL hybrid · portfolio intelligence
        </p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-10 flex flex-col items-center text-center">
        <div className="text-5xl mb-4">🔒</div>
        <h2 className="text-xl font-bold text-gray-800 mb-2">Coming Soon — Phase 2</h2>
        <p className="text-sm text-gray-500 max-w-md mb-6">
          Natural-language querying of your fund portfolio is currently under development.
        </p>
        <ul className="text-sm text-gray-500 text-left space-y-2">
          <li className="flex items-center gap-2">
            <span className="text-indigo-400">·</span>
            RAG retrieval over uploaded fund documents
          </li>
          <li className="flex items-center gap-2">
            <span className="text-indigo-400">·</span>
            Text-to-SQL portfolio-level queries
          </li>
          <li className="flex items-center gap-2">
            <span className="text-indigo-400">·</span>
            Answers scoped per Fund or BLE
          </li>
          <li className="flex items-center gap-2">
            <span className="text-indigo-400">·</span>
            Full audit trail of every AI query
          </li>
        </ul>
      </div>
    </div>
  )
}
