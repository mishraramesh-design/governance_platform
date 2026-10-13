import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/PageHeader";

const TABS = ["Users", "Import CSV", "Teams", "Git authors", "Tokens"];
const SAMPLE = "name,email,team,roles\nAnil Kumar,anil@company.com,Bidding,Developer\nSunita Rao,sunita@company.com,Evaluation;Platform,Tech Lead";
const err = (e) => e.response?.data?.detail?.message || e.response?.data?.detail || "Request failed";

function Btn({ children, ...p }) {
  return <button {...p} className={`text-xs font-bold uppercase border border-black px-3 py-1.5 hover:bg-black hover:text-[#FFE600] disabled:opacity-40 ${p.className || ""}`}>{children}</button>;
}

function Users() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [form, setForm] = useState({ name: "", email: "", teams: "" });
  const { data } = useQuery({ queryKey: ["people", q, page], queryFn: () => api.get("/admin/people", { params: { q, page, page_size: 25 } }).then((r) => r.data) });
  const add = useMutation({
    mutationFn: () => api.post("/admin/users", { name: form.name, email: form.email, teams: form.teams.split(";").map((x) => x.trim()).filter(Boolean), roles: [] }),
    onSuccess: () => { toast.success("User created. Assign roles in Admin · Users & Tokens."); setForm({ name: "", email: "", teams: "" }); qc.invalidateQueries({ queryKey: ["people"] }); },
    onError: (e) => toast.error(err(e)),
  });
  const toggle = useMutation({
    mutationFn: (u) => api.patch(`/admin/users/${u.id}`, { active: !u.active }),
    onSuccess: (r) => { toast.success(r.data.active ? "Reactivated" : `Deactivated, ${r.data.tokens_revoked} token(s) revoked`); qc.invalidateQueries({ queryKey: ["people"] }); },
    onError: (e) => toast.error(err(e)),
  });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-4">
        <input data-testid="people-search" placeholder="Search name or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="border border-gray-400 px-2 py-1 text-sm w-64" />
        <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="border border-gray-400 px-2 py-1 text-sm" />
        <input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="border border-gray-400 px-2 py-1 text-sm" />
        <input placeholder="Teams (a;b)" value={form.teams} onChange={(e) => setForm({ ...form, teams: e.target.value })} className="border border-gray-400 px-2 py-1 text-sm" />
        <Btn data-testid="add-user-btn" disabled={!form.name || !form.email} onClick={() => add.mutate()}>Add user</Btn>
      </div>
      <table className="w-full text-sm border border-gray-200">
        <thead className="bg-gray-50 text-left text-[11px] uppercase tracking-wide"><tr><th className="p-2">Name</th><th>Email</th><th>Teams</th><th>Live tokens</th><th>Status</th><th /></tr></thead>
        <tbody>
          {(data?.users || []).map((u) => (
            <tr key={u.id} className="border-t border-gray-100" data-testid={`person-${u.id}`}>
              <td className="p-2 font-semibold">{u.name}</td><td>{u.email}</td><td>{(u.teams || []).join(", ")}</td><td>{u.live_tokens}</td>
              <td>{u.active ? "Active" : "Inactive"}</td>
              <td><Btn onClick={() => toggle.mutate(u)}>{u.active ? "Deactivate" : "Reactivate"}</Btn></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center gap-3 mt-3 text-xs">
        <Btn disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Btn>
        <span>Page {page} of {pages} · {data?.total ?? 0} users</span>
        <Btn disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Btn>
      </div>
    </div>
  );
}

function ImportCsv() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState(null);
  const prev = useMutation({ mutationFn: () => api.post("/admin/users/import/preview", { csv_text: text }).then((r) => r.data), onSuccess: setPreview, onError: (e) => toast.error(err(e)) });
  const commit = useMutation({
    mutationFn: (skip) => api.post("/admin/users/import/commit", { csv_text: text, skip_errors: skip }).then((r) => r.data),
    onSuccess: (r) => { toast.success(`${r.created.length} users created, ${r.skipped} skipped`); setPreview(null); setText(""); qc.invalidateQueries({ queryKey: ["people"] }); },
    onError: (e) => toast.error(typeof err(e) === "string" ? err(e) : "Fix the errors first"),
  });
  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">Columns: name, email, team, roles. Several teams or roles separated by ; Roles are applied to every project; refine afterwards in Admin · Users &amp; Tokens.</p>
      <textarea data-testid="csv-input" rows={8} value={text} placeholder={SAMPLE} onChange={(e) => { setText(e.target.value); setPreview(null); }} className="w-full border border-gray-400 p-2 font-mono text-xs" />
      <div className="flex gap-2 my-2">
        <Btn data-testid="csv-preview-btn" disabled={!text.trim()} onClick={() => prev.mutate()}>Preview</Btn>
        {preview && preview.errors === 0 && <Btn data-testid="csv-commit-btn" onClick={() => commit.mutate(false)}>Create {preview.ok} users</Btn>}
        {preview && preview.errors > 0 && preview.ok > 0 && <Btn onClick={() => commit.mutate(true)}>Create {preview.ok}, skip {preview.errors} with errors</Btn>}
      </div>
      {preview && (
        <table className="w-full text-xs border border-gray-200">
          <thead className="bg-gray-50 text-left"><tr><th className="p-1">Line</th><th>Name</th><th>Email</th><th>Teams</th><th>Roles</th><th>Result</th></tr></thead>
          <tbody>{preview.rows.map((r) => (
            <tr key={r.line} className={r.status === "error" ? "bg-red-50" : ""}>
              <td className="p-1">{r.line}</td><td>{r.name}</td><td>{r.email}</td><td>{r.teams.join(", ")}</td><td>{r.roles.join(", ")}</td>
              <td>{r.status === "ok" ? "OK" : r.errors.join("; ")}</td>
            </tr>))}</tbody>
        </table>
      )}
    </div>
  );
}

function Teams() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const { data: teams } = useQuery({ queryKey: ["teams"], queryFn: () => api.get("/admin/teams").then((r) => r.data) });
  const { data: adm } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get("/admin/users").then((r) => r.data) });
  const [asg, setAsg] = useState({ team: "", project_id: "", role: "" });
  const create = useMutation({ mutationFn: () => api.post("/admin/teams", { name }), onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["teams"] }); }, onError: (e) => toast.error(err(e)) });
  const assign = useMutation({
    mutationFn: () => api.put("/admin/team-assignments", { team: asg.team, project_id: asg.project_id, roles: [asg.role], mode: "add" }).then((r) => r.data),
    onSuccess: (r) => toast.success(`${r.users_updated} member(s) updated`), onError: (e) => toast.error(err(e)),
  });
  return (
    <div>
      <div className="flex gap-2 mb-4">
        <input placeholder="New team name" value={name} onChange={(e) => setName(e.target.value)} className="border border-gray-400 px-2 py-1 text-sm" />
        <Btn disabled={!name.trim()} onClick={() => create.mutate()}>Create team</Btn>
      </div>
      <table className="w-full text-sm border border-gray-200 mb-6">
        <thead className="bg-gray-50 text-left text-[11px] uppercase"><tr><th className="p-2">Team</th><th>Members</th></tr></thead>
        <tbody>{(teams || []).map((t) => <tr key={t.id} className="border-t border-gray-100"><td className="p-2">{t.name}</td><td>{t.members}</td></tr>)}</tbody>
      </table>
      <h3 className="text-xs font-bold uppercase mb-2">Give a team a role on a project</h3>
      <div className="flex flex-wrap gap-2">
        <select value={asg.team} onChange={(e) => setAsg({ ...asg, team: e.target.value })} className="border border-gray-400 px-2 py-1 text-sm"><option value="">Team</option>{(teams || []).map((t) => <option key={t.id}>{t.name}</option>)}</select>
        <select value={asg.project_id} onChange={(e) => setAsg({ ...asg, project_id: e.target.value })} className="border border-gray-400 px-2 py-1 text-sm"><option value="">Project</option>{(adm?.projects || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <select value={asg.role} onChange={(e) => setAsg({ ...asg, role: e.target.value })} className="border border-gray-400 px-2 py-1 text-sm"><option value="">Role</option>{(adm?.roles || []).map((r) => <option key={r}>{r}</option>)}</select>
        <Btn disabled={!asg.team || !asg.project_id || !asg.role} onClick={() => assign.mutate()}>Add role to team</Btn>
      </div>
    </div>
  );
}

function Authors() {
  const qc = useQueryClient();
  const { data: unmapped } = useQuery({ queryKey: ["unmapped"], queryFn: () => api.get("/admin/unmapped-authors").then((r) => r.data) });
  const { data: aliases } = useQuery({ queryKey: ["aliases"], queryFn: () => api.get("/admin/aliases").then((r) => r.data) });
  const { data: people } = useQuery({ queryKey: ["people-all"], queryFn: () => api.get("/admin/people", { params: { page_size: 200 } }).then((r) => r.data) });
  const [pick, setPick] = useState({});
  const map = useMutation({
    mutationFn: ({ alias, user_id }) => api.post("/admin/aliases", { alias, user_id }),
    onSuccess: () => { toast.success("Mapped"); qc.invalidateQueries({ queryKey: ["unmapped"] }); qc.invalidateQueries({ queryKey: ["aliases"] }); },
    onError: (e) => toast.error(err(e)),
  });
  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">Git authors that are not tied to a platform user cannot receive reports and are not covered by the "no self-review" rule.</p>
      <table className="w-full text-sm border border-gray-200 mb-6">
        <thead className="bg-gray-50 text-left text-[11px] uppercase"><tr><th className="p-2">Unmapped author</th><th>Commits</th><th>Map to</th><th /></tr></thead>
        <tbody>{(unmapped || []).map((a) => (
          <tr key={a.author} className="border-t border-gray-100">
            <td className="p-2">{a.author}</td><td>{a.commits}</td>
            <td><select value={pick[a.author] || ""} onChange={(e) => setPick({ ...pick, [a.author]: e.target.value })} className="border border-gray-400 px-2 py-1 text-xs"><option value="">Choose user</option>{(people?.users || []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></td>
            <td><Btn disabled={!pick[a.author]} onClick={() => map.mutate({ alias: a.author, user_id: pick[a.author] })}>Map</Btn></td>
          </tr>))}
          {unmapped && unmapped.length === 0 && <tr><td colSpan={4} className="p-2 text-gray-500">All commit authors are mapped.</td></tr>}
        </tbody>
      </table>
      <h3 className="text-xs font-bold uppercase mb-2">Existing aliases</h3>
      <ul className="text-sm">{(aliases || []).map((a) => <li key={a.id}>{a.alias} → {a.user_id}</li>)}</ul>
    </div>
  );
}

function Tokens() {
  const qc = useQueryClient();
  const [csv, setCsv] = useState("");
  const bulk = useMutation({
    mutationFn: () => api.post("/admin/tokens/bulk", {}).then((r) => r.data),
    onSuccess: (r) => { setCsv(r.csv); toast.success(`${r.issued} token(s) issued. Download now: they are not shown again.`); qc.invalidateQueries({ queryKey: ["people"] }); },
    onError: (e) => toast.error(err(e)),
  });
  const download = () => {
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a"); a.href = url; a.download = "tokens.csv"; a.click(); URL.revokeObjectURL(url);
  };
  return (
    <div>
      <p className="text-xs text-gray-500 mb-3">Issues one token to every active user who has none. Tokens are shown once and only their hashes are stored. Hand each person their own token privately.</p>
      <Btn data-testid="bulk-token-btn" onClick={() => bulk.mutate()}>Issue tokens to users without one</Btn>
      {csv && <div className="mt-3"><Btn onClick={download}>Download tokens.csv</Btn> <span className="text-xs text-red-600 ml-2">Save it now; closing this page loses it.</span></div>}
    </div>
  );
}

export default function People() {
  const { isAdmin, ready } = useAuth();
  const [tab, setTab] = useState(TABS[0]);
  if (ready && !isAdmin) return <div className="p-6 text-sm">Programme Manager access required.</div>;
  return (
    <div data-testid="people-page">
      <PageHeader title="People & Teams" subtitle="Create users, import a team from CSV, group people into teams, map git authors, and issue tokens. Programme Manager only." />
      <div className="flex gap-1 mb-5 border-b border-gray-200">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-xs font-bold uppercase border-b-4 ${tab === t ? "border-[#FFE600] text-black" : "border-transparent text-gray-500"}`}>{t}</button>
        ))}
      </div>
      {tab === "Users" && <Users />}
      {tab === "Import CSV" && <ImportCsv />}
      {tab === "Teams" && <Teams />}
      {tab === "Git authors" && <Authors />}
      {tab === "Tokens" && <Tokens />}
    </div>
  );
}
