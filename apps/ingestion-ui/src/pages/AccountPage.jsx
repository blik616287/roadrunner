import { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';

const API = '/api';

export default function AccountPage() {
  const { user } = useAuth();
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [rotationDays, setRotationDays] = useState('');
  const [newKey, setNewKey] = useState(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');

  const fetchKeys = () => {
    fetch(`${API}/auth/api-keys`)
      .then((r) => r.json())
      .then((data) => setKeys(data.keys || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchKeys();
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError('');
    try {
      const res = await fetch(`${API}/auth/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          rotation_days: rotationDays ? parseInt(rotationDays) : null,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setNewKey(data.raw_key);
      setName('');
      setRotationDays('');
      fetchKeys();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId) => {
    if (!confirm('Revoke this API key? This cannot be undone.')) return;
    await fetch(`${API}/auth/api-keys/${keyId}`, { method: 'DELETE' });
    fetchKeys();
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(newKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getStatus = (key) => {
    if (key.revoked_at) return 'revoked';
    if (key.expires_at && new Date(key.expires_at) < new Date()) return 'expired';
    return 'active';
  };

  const statusColor = {
    active: 'bg-green-100 text-green-700',
    expired: 'bg-yellow-100 text-yellow-700',
    revoked: 'bg-red-100 text-red-700',
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold">Account</h1>

      {/* Profile */}
      <div className="bg-white border rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-500 mb-3">Profile</h2>
        <div className="flex items-center gap-3">
          {user?.picture && (
            <img src={user.picture} alt="" className="w-10 h-10 rounded-full" />
          )}
          <div>
            <div className="font-medium">{user?.name || 'User'}</div>
            <div className="text-sm text-gray-500">{user?.email}</div>
          </div>
        </div>
      </div>

      {/* New key reveal modal */}
      {newKey && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-5">
          <h3 className="text-sm font-medium text-blue-800 mb-2">API Key Created</h3>
          <p className="text-xs text-blue-600 mb-3">
            Copy this key now. It will not be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-white border rounded px-3 py-2 text-sm font-mono break-all">
              {newKey}
            </code>
            <button
              onClick={handleCopy}
              className="px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 shrink-0"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <button
            onClick={() => setNewKey(null)}
            className="mt-3 text-xs text-blue-600 hover:text-blue-800"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Create API key */}
      <div className="bg-white border rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-500 mb-3">Create API Key</h2>
        <form onSubmit={handleCreate} className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. CI pipeline"
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="w-40">
            <label className="block text-xs text-gray-500 mb-1">Rotation</label>
            <select
              value={rotationDays}
              onChange={(e) => setRotationDays(e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">No expiry</option>
              <option value="30">30 days</option>
              <option value="60">60 days</option>
              <option value="90">90 days</option>
              <option value="180">180 days</option>
              <option value="365">1 year</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={creating || !name.trim()}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {creating ? 'Creating...' : 'Create'}
          </button>
        </form>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      {/* API keys table */}
      <div className="bg-white border rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-500 mb-3">API Keys</h2>
        {loading ? (
          <p className="text-sm text-gray-400">Loading...</p>
        ) : keys.length === 0 ? (
          <p className="text-sm text-gray-400">No API keys yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b">
                <th className="pb-2 font-medium">Name</th>
                <th className="pb-2 font-medium">Key</th>
                <th className="pb-2 font-medium">Created</th>
                <th className="pb-2 font-medium">Expires</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => {
                const status = getStatus(k);
                return (
                  <tr key={k.id} className="border-b last:border-0">
                    <td className="py-2">{k.name}</td>
                    <td className="py-2 font-mono text-xs text-gray-500">
                      {k.key_prefix}...
                    </td>
                    <td className="py-2 text-gray-500">
                      {new Date(k.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-2 text-gray-500">
                      {k.expires_at
                        ? new Date(k.expires_at).toLocaleDateString()
                        : 'Never'}
                    </td>
                    <td className="py-2">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor[status]}`}
                      >
                        {status}
                      </span>
                    </td>
                    <td className="py-2 text-right">
                      {status === 'active' && (
                        <button
                          onClick={() => handleRevoke(k.id)}
                          className="text-xs text-red-600 hover:text-red-800"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
