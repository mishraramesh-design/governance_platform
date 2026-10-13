import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

export default function Admin() {
  const { isAdmin, ready } = useAuth();
  const qc = useQueryClient();
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [issuedToken, setIssuedToken] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get("/admin/users").then((r) => r.data),
    enabled: ready && isAdmin,
    retry: false,
  });

  const setAssignment = useMutation({
    mutationFn: (body) => api.put("/admin/assignments", body),
    onSuccess: () => {
      toast.success("Role assignment updated");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => toast.error(err.response?.data?.detail || "Update failed"),
  });

  const issueToken = useMutation({
    mutationFn: (user_id) => api.post("/admin/tokens", { user_id }).then((r) => r.data),
    onSuccess: (res) => {
      setIssuedToken(res.token);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => toast.error(err.response?.data?.detail || "Issue failed"),
  });

  const revokeToken = useMutation({
    mutationFn: (token_id) => api.post(`/admin/tokens/${token_id}/revoke`),
    onSuccess: () => {
      toast.success("Token revoked");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => toast.error(err.response?.data?.detail || "Revoke failed"),
  });

  if (ready && !isAdmin) {
    return (
      <div data-testid="admin-gate" className="max-w-xl">
        <PageHeader title="Administration" subtitle="Restricted area." />
        <div className="border-l-4 border-[#FFE600] bg-gray-50 p-4 text-sm">
          <span className="font-bold">Programme Manager access required.</span> Sign in as the
          Programme Manager (top-right user switcher) to manage role assignments and API tokens.
        </div>
      </div>
    );
  }

  if (isLoading || !ready) return <div className="text-sm text-gray-400">Loading…</div>;
  if (error) return <div className="text-sm text-red-600">Failed to load admin data.</div>;

  const { users = [], projects = [], roles = [] } = data || {};
  const selectedUser = users.find((u) => u.id === selectedUserId);

  const rolesFor = (user, projectId) => {
    const a = (user.assignments || []).find((x) => x.project_id === projectId);
    return a ? a.roles : [];
  };

  const toggleRole = (user, projectId, role) => {
    const current = rolesFor(user, projectId);
    const next = current.includes(role) ? current.filter((r) => r !== role) : [...current, role];
    setAssignment.mutate({ user_id: user.id, project_id: projectId, roles: next });
  };

  return (
    <div data-testid="admin-page">
      <PageHeader title="Admin · Users & Tokens" subtitle="Manage per-project role assignments and issue or revoke opaque API tokens. Tokens are shown once at issuance; only their SHA-256 hash is stored." />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 border border-gray-200">
          <div className="px-3 py-2 text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 border-b border-gray-200">Users ({users.length})</div>
          {users.map((u) => (
            <button
              key={u.id}
              data-testid={`admin-user-${u.id}`}
              onClick={() => setSelectedUserId(u.id)}
              className={`w-full text-left px-3 py-2.5 border-b border-gray-100 transition-colors duration-100 ${selectedUserId === u.id ? "bg-gray-50 border-l-4 border-l-[#FFE600]" : "hover:bg-gray-50 border-l-4 border-l-transparent"}`}
            >
              <div className="text-sm font-bold">{u.name}</div>
              <div className="text-xs text-gray-500">{u.email}</div>
              <div className="text-[10px] text-gray-400">{(u.tokens || []).filter((t) => !t.revoked).length} active token(s)</div>
            </button>
          ))}
        </div>

        <div className="lg:col-span-2">
          {!selectedUser && <div className="text-sm text-gray-400 italic">Select a user to manage roles and tokens.</div>}
          {selectedUser && (
            <div className="space-y-6" data-testid="admin-user-detail">
              <div className="flex items-center justify-between gap-3 border-b border-gray-200 pb-3">
                <div>
                  <div className="text-lg font-bold font-[Chivo]">{selectedUser.name}</div>
                  <div className="text-xs text-gray-500">{selectedUser.email}</div>
                </div>
                <button
                  data-testid="issue-token-btn"
                  onClick={() => issueToken.mutate(selectedUser.id)}
                  className="border border-black text-xs font-bold uppercase px-3 py-2 hover:bg-black hover:text-[#FFE600] transition-colors duration-100"
                >
                  Issue API token
                </button>
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Role assignments per project</div>
                <div className="space-y-4">
                  {projects.map((p) => (
                    <div key={p.id} className="border border-gray-200 p-3">
                      <div className="text-sm font-bold mb-2">{p.name} <span className="text-[10px] text-gray-400 font-normal">Tier {p.integrity_tier}</span></div>
                      <div className="flex flex-wrap gap-2">
                        {roles.map((r) => {
                          const on = rolesFor(selectedUser, p.id).includes(r);
                          return (
                            <button
                              key={r}
                              data-testid={`role-toggle-${p.id}-${r}`}
                              onClick={() => toggleRole(selectedUser, p.id, r)}
                              className={`text-[11px] font-semibold px-2 py-1 border transition-colors duration-100 ${on ? "bg-black text-[#FFE600] border-black" : "bg-white text-gray-600 border-gray-300 hover:border-black"}`}
                            >
                              {r}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">API tokens</div>
                <div className="space-y-2">
                  {(selectedUser.tokens || []).length === 0 && <div className="text-xs text-gray-400 italic">No tokens issued.</div>}
                  {(selectedUser.tokens || []).map((t) => (
                    <div key={t.id} data-testid={`token-row-${t.id}`} className="flex items-center justify-between gap-3 border border-gray-200 px-3 py-2 text-xs">
                      <div>
                        <span className="font-mono">{t.id}</span>
                        <span className="text-gray-400 ml-2">by {t.created_by}</span>
                        {t.revoked && <span className="ml-2 font-bold text-red-600 uppercase">revoked</span>}
                      </div>
                      {!t.revoked && (
                        <button
                          data-testid={`revoke-token-btn-${t.id}`}
                          onClick={() => revokeToken.mutate(t.id)}
                          className="border border-red-500 text-red-600 text-[10px] font-bold uppercase px-2 py-1 hover:bg-red-600 hover:text-white transition-colors duration-100"
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <Dialog open={!!issuedToken} onOpenChange={(o) => !o && setIssuedToken(null)}>
        <DialogContent data-testid="issued-token-dialog">
          <DialogHeader>
            <DialogTitle>API token issued</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-gray-600">Copy this token now — it is shown only once and cannot be retrieved again.</p>
          <div data-testid="issued-token-value" className="font-mono text-xs break-all border border-black bg-gray-50 p-3 select-all">{issuedToken}</div>
          <button
            onClick={() => { navigator.clipboard?.writeText(issuedToken); toast.success("Copied"); }}
            className="border border-black text-xs font-bold uppercase px-3 py-2 hover:bg-black hover:text-[#FFE600] transition-colors duration-100"
          >
            Copy to clipboard
          </button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
