import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(true);

  useEffect(() => {
    fetch('/api/auth/me')
      .then((r) => {
        if (r.status === 404) {
          // Auth endpoints don't exist
          setAuthEnabled(false);
          setUser({ email: 'anonymous@local', name: 'Anonymous' });
          return null;
        }
        if (r.ok) return r.json();
        // 401 = auth enabled but not logged in
        return null;
      })
      .then((data) => {
        if (data) {
          if (data.auth_enabled === false) {
            setAuthEnabled(false);
            setUser({ email: data.email, name: data.name, picture: data.picture });
          } else {
            setUser(data);
          }
        }
      })
      .catch(() => {
        setAuthEnabled(false);
        setUser({ email: 'anonymous@local', name: 'Anonymous' });
      })
      .finally(() => setLoading(false));
  }, []);

  const logout = () => {
    fetch('/api/auth/logout', { method: 'POST' }).then(() => {
      setUser(null);
      window.location.href = '/login';
    });
  };

  return (
    <AuthContext.Provider value={{ user, loading, authEnabled, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
