import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Command Centre', icon: '📊' },
  { to: '/reviews', label: 'Suggested Reviews', icon: '💼' },
  { to: '/copilot', label: 'Copilot / Ask', icon: '🤖', comingSoon: true },
]

export function Sidebar() {
  const [adminOpen, setAdminOpen] = useState(false)
  const location = useLocation()
  const adminActive = location.pathname.startsWith('/admin')

  return (
    <aside className="fixed top-0 left-0 h-screen w-56 bg-gray-900 text-white flex flex-col z-10">
      <div className="px-4 py-5 border-b border-gray-700">
        <div className="text-xs font-bold tracking-widest text-gray-400 uppercase">Fund EI</div>
        <div className="text-sm text-gray-300 mt-0.5">KYB Compliance Platform</div>
      </div>
      <nav className="flex-1 py-4 space-y-0.5">
        {NAV.map(({ to, label, icon, comingSoon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                isActive
                  ? 'bg-indigo-700 text-white font-semibold'
                  : 'text-gray-300 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            <span className="text-base">{icon}</span>
            <span className="flex-1">{label}</span>
            {comingSoon && (
              <span className="text-[10px] font-bold bg-amber-400 text-amber-900 px-1.5 py-0.5 rounded-full leading-none">
                Soon
              </span>
            )}
          </NavLink>
        ))}

        {/* Admin collapsible */}
        <button
          onClick={() => setAdminOpen(o => !o)}
          className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
            adminActive
              ? 'bg-indigo-700 text-white font-semibold'
              : 'text-gray-300 hover:bg-gray-800 hover:text-white'
          }`}
        >
          <span className="text-base">⚙️</span>
          <span className="flex-1 text-left">Admin</span>
          <span className="text-xs">{adminOpen ? '▼' : '▶'}</span>
        </button>
        {adminOpen && (
          <NavLink
            to="/admin/ruleset"
            className={({ isActive }) =>
              `flex items-center gap-3 pl-10 pr-4 py-2 text-sm transition-colors ${
                isActive
                  ? 'bg-indigo-600 text-white font-semibold'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            Ruleset Builder
          </NavLink>
        )}
      </nav>
      <div className="px-4 py-3 border-t border-gray-700 text-xs text-gray-500">
        v1 · KYB Platform
      </div>
    </aside>
  )
}
