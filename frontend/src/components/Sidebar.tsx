import { NavLink } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Command Centre', icon: '📊' },
  { to: '/reviews', label: 'Suggested Reviews', icon: '💼' },
  { to: '/copilot', label: 'Copilot / Ask', icon: '🤖' },
  { to: '/admin/ruleset', label: 'Ruleset Builder', icon: '⚙️' },
  { to: '/evals', label: 'Eval Dashboard', icon: '📈' },
]

export function Sidebar() {
  return (
    <aside className="fixed top-0 left-0 h-screen w-56 bg-gray-900 text-white flex flex-col z-10">
      <div className="px-4 py-5 border-b border-gray-700">
        <div className="text-xs font-bold tracking-widest text-gray-400 uppercase">Fund EI</div>
        <div className="text-sm text-gray-300 mt-0.5">KYB Compliance Platform</div>
      </div>
      <nav className="flex-1 py-4 space-y-0.5">
        {NAV.map(({ to, label, icon }) => (
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
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-gray-700 text-xs text-gray-500">
        MOCK mode · v1
      </div>
    </aside>
  )
}
