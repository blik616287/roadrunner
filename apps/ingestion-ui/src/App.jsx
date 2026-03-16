import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { AuthProvider, useAuth } from './hooks/useAuth';
import { WorkspaceProvider } from './hooks/useWorkspaceContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import DataPage from './pages/DataPage';
import GraphPage from './pages/GraphPage';
import QueryPage from './pages/QueryPage';
import AccountPage from './pages/AccountPage';

function RequireAuth() {
  const { user, loading, authEnabled } = useAuth();
  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen text-gray-400">
        Loading...
      </div>
    );
  }
  if (!authEnabled) return <Outlet />;
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export default function App() {
  return (
    <AuthProvider>
      <WorkspaceProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<Layout />}>
                <Route index element={<DashboardPage />} />
                <Route path="data" element={<DataPage />} />
                <Route path="graph" element={<GraphPage />} />
                <Route path="query" element={<QueryPage />} />
                <Route path="account" element={<AccountPage />} />
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
      </WorkspaceProvider>
    </AuthProvider>
  );
}
