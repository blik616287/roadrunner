import { NavLink, Outlet, useLocation } from 'react-router-dom';
import WorkspaceSelector from './WorkspaceSelector';
import { useAuth } from '../hooks/useAuth';

const nav = [
  { to: '/', label: 'Dashboard' },
  { to: '/data', label: 'Data' },
  { to: '/graph', label: 'Graph' },
  { to: '/query', label: 'Query' },
  { to: '/account', label: 'Account' },
];

export default function Layout() {
  const isDashboard = useLocation().pathname === '/';
  const { user, authEnabled, logout } = useAuth();
  return (
    <div className="flex h-screen bg-gray-50 text-gray-900">
      <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col shrink-0">
        <div className="px-4 py-5 text-lg font-bold tracking-tight border-b border-gray-700">
          GraphRAG
        </div>
        <nav className="flex-1 p-2 space-y-0.5">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm ${
                  isActive ? 'bg-gray-700 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        {authEnabled && user && (
          <div className="p-3 border-t border-gray-700">
            <div className="flex items-center gap-2 mb-2">
              {user.picture && (
                <img src={user.picture} alt="" className="w-6 h-6 rounded-full" />
              )}
              <span className="text-gray-300 text-sm truncate">{user.email}</span>
            </div>
            <button
              onClick={logout}
              className="text-gray-400 hover:text-white text-xs"
            >
              Sign out
            </button>
          </div>
        )}
      </aside>
      <div className="flex-1 flex flex-col overflow-hidden">
        {!isDashboard && (
          <header className="flex items-center gap-3 px-6 py-3 border-b bg-white shrink-0">
            <WorkspaceSelector />
          </header>
        )}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
