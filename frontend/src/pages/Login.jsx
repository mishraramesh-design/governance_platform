import { useState } from "react";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { signInWithToken } = useAuth();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signInWithToken(token);
    } catch {
      setError("That token is not valid, or it has been revoked. Ask your Programme Manager for a new one.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-white flex items-center justify-center px-4" data-testid="login-page">
      <form onSubmit={submit} className="w-full max-w-md border border-black p-8">
        <div className="relative w-8 h-8 bg-black mb-4"><span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-[#FFE600]" /></div>
        <h1 className="font-[Chivo] font-black text-xl tracking-tight">IV&amp;V GOVERNANCE</h1>
        <p className="text-xs uppercase tracking-[0.2em] text-gray-400 mb-6">Observe · Evidence · Advise</p>
        <label className="block text-xs font-bold uppercase tracking-wide mb-1" htmlFor="token">Access token</label>
        <input
          id="token"
          data-testid="login-token-input"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="w-full border border-gray-400 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          placeholder="Paste the token issued to you"
        />
        {error && <p data-testid="login-error" className="text-xs text-red-600 mt-2">{error}</p>}
        <button
          data-testid="login-submit"
          disabled={!token.trim() || busy}
          className="mt-5 w-full bg-black text-white text-sm font-bold py-2 hover:bg-[#FFE600] hover:text-black disabled:opacity-40"
        >
          {busy ? "Checking…" : "Sign in"}
        </button>
        <p className="text-[11px] text-gray-500 mt-4">Tokens are issued by your Programme Manager. This platform is read-only toward your systems and advisory only.</p>
      </form>
    </div>
  );
}
