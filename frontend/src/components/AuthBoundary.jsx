import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../context/AuthContext';
import api from '../lib/api';

export function AuthBoundary({ children }) {
  const { ready, isAuthenticated, signInWithToken, signInAs, demoMode, user } = useAuth();
  const [token, setToken] = useState('');
  const [users, setUsers] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();
  useEffect(() => { queryClient.clear(); }, [user?.id, queryClient]);
  useEffect(() => {
    if (demoMode) api.get('/auth/users').then(r => setUsers(r.data)).catch(() => setUsers([]));
  }, [demoMode]);
  if (!ready) return <div className="p-8" role="status">Checking session…</div>;
  if (isAuthenticated) return children;
  const login = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try { await signInWithToken(token); setToken(''); }
    catch { setError('The access token is invalid, revoked, or its user is inactive.'); }
    finally { setBusy(false); }
  };
  return <main className="min-h-screen flex items-center justify-center p-6 bg-gray-50">
    <section className="w-full max-w-md border border-gray-300 bg-white p-8">
      <h1 className="text-2xl font-bold">Governance AI Studio</h1>
      <p className="text-sm text-gray-600 mt-2">Sign in with your issued access token.</p>
      <form onSubmit={login} className="mt-6 space-y-4">
        <label className="block text-sm font-semibold">Access token<input name="access-token" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required className="block w-full border p-3 mt-2" /></label>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <button disabled={busy || !token.trim()} className="bg-black text-[#FFE600] w-full p-3 disabled:opacity-40">{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      {demoMode && <label className="block mt-6 text-sm">Explicit demo mode<select aria-label="Demo identity" defaultValue="" disabled={busy} onChange={async e => {
        if (!e.target.value) return;
        setBusy(true); setError('');
        try { await signInAs(e.target.value); } catch { setError('Demo sign-in failed.'); } finally { setBusy(false); }
      }} className="block w-full border p-2 mt-2"><option value="">Choose a demo identity</option>{users.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}
    </section>
  </main>;
}
