import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import api from '../lib/api';
import { useProject } from '../context/ProjectContext';

const base = '/testing-workspace/sessions';
const button = 'px-3 py-2 text-xs font-semibold border border-gray-300 hover:bg-gray-100 disabled:opacity-40';
const primary = `${button} bg-black text-[#FFE600] hover:bg-gray-800`;
const editable = ['plan_review', 'paused', 'handoff', 'completed'];
const takeoverStates = ['plan_review', 'paused', 'handoff'];

function Evidence({ sessionId, evidence }) {
  const [image, setImage] = useState('');
  const [open, setOpen] = useState(false);
  const evidenceId = evidence?.id;
  useEffect(() => {
    if (!open || !evidenceId) return undefined;
    let active = true;
    let objectUrl;
    api.get(`${base}/${sessionId}/evidence/${evidenceId}`, { responseType: 'blob' }).then((response) => {
      objectUrl = URL.createObjectURL(response.data);
      if (active) setImage(objectUrl);
    }).catch(() => toast.error('Evidence could not be loaded'));
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [open, sessionId, evidenceId]);
  return <div className="mt-2"><button type="button" className="text-blue-700 underline" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'View'} screenshot evidence</button>{open && image && <img src={image} alt="Captured test result evidence" className="mt-2 border w-full" />}</div>;
}

export default function TestingWorkspace() {
  const { projectId, currentProject } = useProject();
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(() => sessionStorage.getItem('testing_workspace_session') || '');
  const [session, setSession] = useState(null);
  const [browser, setBrowser] = useState(null);
  const [browserError, setBrowserError] = useState('');
  const [statusError, setStatusError] = useState('');
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(!sessionId);
  const [planOpen, setPlanOpen] = useState(false);
  const [planJson, setPlanJson] = useState('');
  const [chat, setChat] = useState('');
  const [secure, setSecure] = useState(false);
  const [selectedNode, setSelectedNode] = useState('focused');
  const [form, setForm] = useState({ name: '', url: '', authorization_owner: '', authorization_reference: '',
    authorized: false, allow_cloud: false, allowed_origins: '', requirements: '' });
  const [files, setFiles] = useState([]);
  const feed = useRef(null);
  const previousPlan = useRef('');
  const browserEnabled = Boolean(session && !['closed', 'interrupted'].includes(session.status));

  const refreshList = useCallback(() => api.get(base).then((response) => setSessions(response.data)).catch(() => {}), []);
  useEffect(() => { refreshList(); }, [refreshList]);
  useEffect(() => {
    if (!sessionId) return undefined;
    sessionStorage.setItem('testing_workspace_session', sessionId);
    let active = true;
    let timer;
    const poll = async () => {
      try {
        const response = await api.get(`${base}/${sessionId}`);
        if (!active) return;
        setSession(response.data); setStatusError('');
        const digest = response.data.plan_hash || '';
        if (previousPlan.current !== `${sessionId}:${digest}`) {
          previousPlan.current = `${sessionId}:${digest}`;
          setPlanJson(JSON.stringify(response.data.plan || { cases: [] }, null, 2));
        }
      } catch (error) {
        if (active) setStatusError(error?.response?.data?.detail || 'Live session status is unavailable.');
      }
      if (active) timer = setTimeout(poll, 2000);
    };
    setSession(null); setBrowser(null); setBrowserError('');
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !browserEnabled) return undefined;
    let active = true;
    let timer;
    const poll = async () => {
      try {
        const response = await api.get(`${base}/${sessionId}/browser`);
        if (active) { setBrowser(response.data); setBrowserError(''); }
      } catch (error) {
        if (active) setBrowserError(error?.response?.data?.detail || 'Browser stream unavailable.');
      }
      if (active) timer = setTimeout(poll, 2000);
    };
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, [sessionId, browserEnabled]);

  useEffect(() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [session?.events?.length]);
  useEffect(() => { setSelectedNode('focused'); }, [browser?.observation_id]);

  const act = async (path, data = {}) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post(`${base}/${sessionId}/${path}`, data);
      const response = await api.get(`${base}/${sessionId}`);
      setSession(response.data);
      refreshList();
    } catch (error) { toast.error(error?.response?.data?.detail || 'Workspace action could not be completed'); }
    finally { setBusy(false); }
  };

  const create = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      const body = new FormData();
      body.append('project_id', projectId || '');
      Object.entries(form).forEach(([key, value]) => body.append(key, String(value)));
      files.forEach((file) => body.append('files', file));
      const response = await api.post(base, body);
      setSessionId(response.data.id); setCreateOpen(false); setFiles([]); refreshList();
      toast.success('Browser workspace opened; preparing the plan');
    } catch (error) { toast.error(error?.response?.data?.detail || 'Could not open the testing workspace'); }
    finally { setBusy(false); }
  };

  const send = async (event) => {
    event.preventDefault();
    if ((secure ? !chat.length : !chat.trim()) || !sessionId) return;
    const value = chat;
    setChat('');
    if (secure) {
      await act('input', { op: 'fill', node: selectedNode, value, secret: true, observation_id: browser?.observation_id || '' });
    } else await act('chat', { text: value });
  };

  const downloadReport = async () => {
    try {
      const response = await api.get(`${base}/${sessionId}/report`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(response.data, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = `workspace-${sessionId}.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { toast.error('Report could not be downloaded'); }
  };

  const takeOver = session && takeoverStates.includes(session.status);
  const field = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }));
  let draftPlan = null;
  try { draftPlan = JSON.parse(planJson); } catch { /* Advanced edits may be temporarily incomplete. */ }
  const editCase = (index, key, value) => {
    if (!draftPlan?.cases) return;
    const cases = draftPlan.cases.map((item, position) => position === index ? { ...item, [key]: value } : item);
    setPlanJson(JSON.stringify({ ...draftPlan, cases }, null, 2));
  };

  return <div className="space-y-4" data-testid="testing-workspace">
    <header className="flex flex-wrap justify-between gap-3 items-start border-b pb-4">
      <div><p className="text-[10px] font-bold tracking-widest text-gray-500 uppercase">Governance AI Studio</p>
        <h1 className="text-2xl font-bold">AI Testing Workspace</h1><p className="text-sm text-gray-600 mt-1">Review the plan. Watch the browser. Approve changes. Follow every result.</p></div>
      <div className="flex gap-2"><Link to="/studio" className={button}>Governance Studio</Link><button type="button" className={primary} onClick={() => setCreateOpen(!createOpen)}>New session</button></div>
    </header>
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-xs font-semibold">Session <select disabled={busy} aria-label="Testing session" className="border p-2 ml-2 max-w-xs" value={sessionId} onChange={(event) => setSessionId(event.target.value)}><option value="">Choose a session</option>{sessions.map((item) => <option key={item.id} value={item.id}>{item.name} - {item.status}</option>)}</select></label>
      {session && <><span className="px-2 py-1 text-xs font-bold bg-yellow-100 uppercase" role="status">{session.status.replaceAll('_', ' ')}</span><button type="button" className={button} onClick={downloadReport}>Download report</button><button type="button" className={button} disabled={busy || session.status === 'closed'} onClick={() => act('close')}>Close browser</button></>}
    </div>
    {createOpen && <form onSubmit={create} className="border bg-gray-50 p-4 space-y-3" data-testid="workspace-intake">
      <h2 className="font-bold">Start an authorized browser assessment</h2>
      <p className="text-xs text-gray-600">Model settings: {currentProject?.name || 'Studio defaults'} (maker profile)</p>
      <div className="grid md:grid-cols-2 gap-3">{[['name', 'Assessment name'], ['url', 'Application URL'], ['authorization_owner', 'Authorizing owner'], ['authorization_reference', 'Approval or ticket reference']].map(([key, label]) => <label key={key} className="text-xs font-semibold">{label}<input required maxLength={key === 'url' ? 2048 : 300} type={key === 'url' ? 'url' : 'text'} value={form[key]} onChange={field(key)} className="block border bg-white p-2 w-full mt-1" /></label>)}</div>
      <label className="block text-xs font-semibold">Excel test cases and/or SRS (up to four files; 2 MB each)<input type="file" multiple accept=".xlsx,.txt,.md,.csv,.docx,.pdf" className="block mt-1" onChange={(event) => setFiles(Array.from(event.target.files || []))} /></label>
      <a href="/workspace-test-cases.xlsx" download className="text-xs underline text-blue-700">Download Excel test-case template (replace example expectations)</a>
      <label className="block text-xs font-semibold">Requirements or test instructions<textarea maxLength={50000} rows={3} className="block border w-full p-2 mt-1" value={form.requirements} onChange={field('requirements')} /></label>
      <label className="block text-xs font-semibold">Additional approved origins for SSO/CDN (one full origin per line; optional)<textarea rows={2} className="block border w-full p-2 mt-1" placeholder="https://login.your-company.example" value={form.allowed_origins} onChange={field('allowed_origins')} /></label>
      <label className="flex items-start gap-2 text-xs"><input required type="checkbox" checked={form.authorized} onChange={field('authorized')} />I have owner authorization for functional testing of these exact origins in an isolated test environment. I will approve application data changes.</label>
      <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={form.allow_cloud} onChange={field('allow_cloud')} />Allow masked document and visible page text to be sent to the cloud model configured in Studio. Otherwise use a local model only. Masking may not remove all sensitive data.</label>
      <p className="text-xs text-gray-500">Form fields are masked in screenshots. Screenshots can contain other visible application data and are retained as owner-only evidence. Raw uploads and browser cookies are not retained.</p>
      <button className={primary} disabled={busy}>{busy ? 'Opening browser...' : 'Open browser and draft plan'}</button>
    </form>}
    {statusError && <p role="alert" className="border border-red-300 bg-red-50 p-3 text-sm">{statusError}</p>}
    {session && <div className="grid xl:grid-cols-[minmax(340px,0.85fr)_minmax(500px,1.3fr)] gap-4 items-start">
      <section className="border flex flex-col bg-white" aria-label="AI chat and test outcomes">
        <div className="p-3 border-b bg-gray-50 flex justify-between items-center"><div><h2 className="font-bold text-sm">Agent conversation &amp; results</h2><p className="text-[10px] text-gray-500">Studio maker model - approvals stay with you</p></div><Link to="/model-settings" className="text-xs underline">Model settings</Link></div>
        <div className="p-3 flex flex-wrap gap-2 border-b">
          <button type="button" className={button} onClick={() => setPlanOpen(!planOpen)}>Review plan ({session.plan?.cases?.length || 0})</button>
          <button type="button" className={primary} disabled={busy || !session.approved_plan_hash || !['paused', 'handoff'].includes(session.status)} onClick={() => act('run')}>Run / Resume tests</button>
          <button type="button" className={button} disabled={busy || ['closed', 'interrupted'].includes(session.status)} onClick={() => act('pause')}>Pause &amp; take over</button>
          {session.current_case_id && ['paused', 'handoff', 'awaiting_action'].includes(session.status) && !session.results?.some((item) => item.case_id === session.current_case_id) && <button type="button" className={button} disabled={busy} onClick={() => act('skip', { case_id: session.current_case_id })}>Skip {session.current_case_id} as blocked</button>}
        </div>
        {planOpen && <div className="p-3 space-y-2 border-b bg-blue-50">
          <p className="text-xs">Review the linked sources, test steps and expected outcomes. Set an exact visible-text or URL check for each functional test. Tests without a check remain BLOCKED. Editing requires fresh approval.</p>
          <p className="text-xs font-semibold">{session.plan?.use_cases?.length || 0} use cases - {session.plan?.cases?.length || 0} test cases - {session.sources?.filter((source) => !session.plan?.cases?.some((test) => test.source_ids.includes(source.id))).length || 0} sources without mapped tests</p>
          <details className="text-xs"><summary className="cursor-pointer font-semibold">Source register ({session.sources?.length || 0})</summary><div className="max-h-60 overflow-auto space-y-2 mt-2">{session.sources?.map((source) => <p key={source.id} className="border-b pb-2"><strong>{source.id}</strong> - {source.location}<br />{source.text}</p>)}</div></details>
          {!!draftPlan?.use_cases?.length && <details className="text-xs"><summary className="cursor-pointer font-semibold">Use cases ({draftPlan.use_cases.length})</summary><div className="max-h-64 overflow-auto space-y-3 p-2">{draftPlan.use_cases.map((item) => <article key={item.id} className="border p-2 bg-white"><strong>{item.id}: {item.title}</strong><p>Actor: {item.actor}</p><p className="mt-1">Preconditions: {item.preconditions?.join('; ') || 'Review with owner'}</p><ol className="list-decimal pl-4 mt-1">{item.main_flow?.map((step, index) => <li key={index}>{step}</li>)}</ol><p className="mt-1">Alternates: {item.alternate_flows?.join('; ') || 'None specified'}</p><p className="text-gray-500 mt-1">Sources: {item.source_ids?.join(', ')}</p></article>)}</div></details>}
          <div className="max-h-[560px] overflow-auto space-y-3">{draftPlan?.cases?.map((item, index) => <article key={item.id} className="bg-white border p-3 space-y-2 text-xs">
            <div className="flex justify-between"><strong>{item.id} - {item.category?.replaceAll('_', ' ') || 'functional'}</strong><span className="text-gray-500">{item.use_case_id}</span></div>
            <p className="text-gray-500">Sources: {item.source_ids?.join(', ')}</p>
            <label className="block">Test title<input aria-label={`Title for ${item.id}`} className="border p-2 w-full mt-1" value={item.title || ''} onChange={(event) => editCase(index, 'title', event.target.value)} /></label>
            <label className="block">Steps (one per line)<textarea aria-label={`Steps for ${item.id}`} rows={3} className="border p-2 w-full mt-1" value={item.steps?.join('\n') || ''} onChange={(event) => editCase(index, 'steps', event.target.value.split('\n'))} /></label>
            <label className="block">Expected outcome<textarea aria-label={`Expected outcome for ${item.id}`} rows={2} className="border p-2 w-full mt-1" value={item.expected || ''} onChange={(event) => editCase(index, 'expected', event.target.value)} /></label>
            <label className="block">Execution<select aria-label={`Execution mode for ${item.id}`} className="border p-2 w-full mt-1" value={item.execution || 'agent'} onChange={(event) => editCase(index, 'execution', event.target.value)}><option value="agent">Agent-driven workflow (Studio model)</option><option value="page_assertion">Direct page check (no model calls during execution)</option></select></label>
            {item.execution === 'page_assertion' && <label className="block">Approved page URL<input aria-label={`Page URL for ${item.id}`} type="url" className="border p-2 w-full mt-1" value={item.navigation_url || ''} onChange={(event) => editCase(index, 'navigation_url', event.target.value)} /><span className="text-gray-500">This mode only opens this page and checks the expected text/URL; it does not verify a multi-step workflow.</span></label>}
            <label className="block">How to verify<select aria-label={`Verification type for ${item.id}`} className="border p-2 w-full mt-1" value={item.oracle?.op || ''} onChange={(event) => editCase(index, 'oracle', event.target.value ? { op: event.target.value, value: item.oracle?.value || '' } : null)}><option value="">No approved check - report as blocked</option><option value="assert_text">Exact expected visible text</option><option value="assert_url">Exact expected URL</option></select></label>
            {item.oracle && <label className="block">Expected text or full URL<input aria-label={`Verification value for ${item.id}`} className="border p-2 w-full mt-1" value={item.oracle.value || ''} onChange={(event) => editCase(index, 'oracle', { ...item.oracle, value: event.target.value })} /></label>}
          </article>)}</div>
          <details><summary className="text-xs cursor-pointer">Advanced: edit or copy the full plan</summary><textarea aria-label="Reviewable test plan JSON" rows={12} value={planJson} onChange={(event) => setPlanJson(event.target.value)} className="border p-2 w-full font-mono text-xs mt-2" /></details>
          <div className="flex gap-2"><button type="button" className={primary} disabled={busy || !editable.includes(session.status)} onClick={() => { try { act('approve-plan', { plan: JSON.parse(planJson) }); } catch { toast.error('Plan must be valid JSON'); } }}>Approve this plan</button><button type="button" className={button} disabled={busy || ![...editable, 'error'].includes(session.status)} onClick={() => act('replan')}>Regenerate plan</button></div>
          <p className="text-[10px]">Model: {session.model?.model_used || 'Planning...'} / {session.model?.mode || 'pending'}. Calls: {session.model_budget?.calls_reserved || 0} / {session.model_budget?.limit ?? '?'}. Studio's per-run call ceiling applies to this whole session; increase it in model settings for multi-step tests.</p>
        </div>}
        {session.pending_action && <div className="p-3 bg-amber-50 border-b border-amber-300" role="alert">
          <h3 className="text-sm font-bold">Your approval is required</h3><p className="text-xs mt-1">Test {session.pending_action.case_id}: {session.pending_action.action.op} control {session.pending_action.action.node}</p>
          <p className="text-xs mt-1 whitespace-pre-wrap">{session.pending_action.action.reason}</p>
          <p className="text-xs break-all mt-1">Value: {session.pending_action.action.value || '(none)'}</p>
          <div className="flex gap-2 mt-2"><button className={primary} disabled={busy} onClick={() => act('approve-action', { proposal_id: session.pending_action.id, allow: true })}>Approve once</button><button className={button} disabled={busy} onClick={() => act('approve-action', { proposal_id: session.pending_action.id, allow: false })}>Reject</button></div>
        </div>}
        <div ref={feed} className="overflow-y-auto p-3 space-y-3 h-[420px]" aria-live="polite" aria-label="Live test conversation">
          {(session.events || []).map((item) => <article key={item.id} className={`p-3 text-xs border ${item.kind === 'user' ? 'bg-blue-50 border-blue-100 ml-5' : item.kind === 'result' ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-100 mr-2'}`}><div className="flex justify-between text-[10px] uppercase text-gray-500 mb-1"><strong>{item.kind === 'user' ? 'You' : item.kind}</strong><time>{new Date(item.at).toLocaleTimeString()}</time></div><p className="whitespace-pre-wrap break-words">{item.message}</p></article>)}
          {!session.events?.length && <p className="text-sm text-gray-500">Preparing browser and source documents...</p>}
        </div>
        <form onSubmit={send} className="p-3 border-t space-y-2">
          <div className="flex gap-4 text-xs"><label><input type="radio" checked={!secure} onChange={() => { setSecure(false); setChat(''); }} /> Instruction</label><label><input type="radio" checked={secure} onChange={() => { setSecure(true); setChat(''); }} /> Secure input (password / OTP)</label></div>
          {secure && <><p className="text-xs text-gray-600">Pause first. Click the input in the browser or select a control. The value goes directly to that browser field and is excluded from chat, model prompts and reports.</p><select aria-label="Secure input destination" className="border p-2 text-xs w-full" value={selectedNode} onChange={(event) => setSelectedNode(event.target.value)}><option value="focused">Currently focused input in browser</option>{browser?.controls?.filter((item) => ['input', 'textarea'].includes(item.tag)).map((item) => <option value={item.node} key={item.node}>{item.node}: {item.label || item.type || item.tag}</option>)}</select></>}
          {secure ? <input aria-label="Secure browser input" type="password" autoComplete="off" value={chat} onChange={(event) => setChat(event.target.value)} className="border p-2 w-full text-sm" /> : <textarea aria-label="Instruction to testing agent" maxLength={4000} rows={2} placeholder="Test registration first, skip payments, or explain the next step..." value={chat} onChange={(event) => setChat(event.target.value)} className="border p-2 w-full text-sm" />}
          <button className={primary} disabled={busy || (secure ? !chat.length : !chat.trim()) || session.status === 'closed' || (secure && !takeOver)}>{secure ? 'Enter securely in browser' : 'Send instruction'}</button>
        </form>
        <div className="border-t p-3 space-y-3"><h3 className="font-bold text-xs">Test outcomes ({session.results?.length || 0})</h3>{session.results?.map((result) => <article key={result.id} className="border p-3 text-xs"><div className="flex justify-between gap-2"><strong>{result.case_id}: {result.title}</strong><span className={`font-bold ${result.verdict === 'PASS' ? 'text-green-700' : result.verdict === 'FAIL' ? 'text-red-700' : 'text-amber-700'}`}>{result.verdict}</span></div><p className="mt-2"><strong>Expected:</strong> {result.expected}</p><p className="mt-1"><strong>Actual:</strong> {result.actual}</p><p className="mt-1 text-gray-500">Sources: {result.source_ids.join(', ')} - Ledger {result.ledger?.seq}</p>{result.evidence && <Evidence sessionId={sessionId} evidence={result.evidence} />}</article>)}</div>
      </section>
      <section className="border xl:sticky xl:top-20" aria-label="Live application browser">
        <div className="bg-gray-900 text-white px-3 py-3"><h2 className="text-sm font-bold">Application browser</h2><p className="text-xs font-mono truncate mt-1">{browser?.url || session.url}</p></div>
        <div className="bg-gray-100 flex justify-between gap-2 items-center p-2 text-xs"><span>{takeOver ? 'Takeover enabled: click the browser image' : 'Agent view: pause to take over'}</span><button type="button" className={button} disabled={busy || !takeOver} onClick={() => act('input', { op: 'scroll', value: 'down' })}>Scroll down</button><button type="button" className={button} disabled={busy || !takeOver} onClick={() => act('input', { op: 'scroll', value: 'up' })}>Up</button></div>
        {browserError && <p role="alert" className="bg-red-50 text-red-800 text-xs p-3">{browserError}</p>}
        {browser?.last_action?.ok === false && <p role="alert" className="bg-amber-50 text-amber-900 text-xs p-3">Last browser action did not complete: {browser.last_action.op} ({browser.last_action.error}). Review the target, selected control and any pending approvals.</p>}
        {browser?.frame ? <button type="button" aria-label="Click the remote browser during takeover; keyboard users can select a browser control below" disabled={!takeOver || busy} className="block w-full" onClick={(event) => {
          if (!takeOver || busy) return;
          const rect = event.currentTarget.getBoundingClientRect();
          act('point', { x: Math.min(1279, Math.max(0, Math.floor((event.clientX - rect.left) / rect.width * 1280))), y: Math.min(799, Math.max(0, Math.floor((event.clientY - rect.top) / rect.height * 800))) });
        }}><img data-testid="workspace-browser-frame" src={`data:image/jpeg;base64,${browser.frame}`} alt="Live remote browser; form values are masked" className={`w-full ${takeOver ? 'cursor-crosshair' : ''}`} /></button> : <div className="h-80 flex items-center justify-center text-sm text-gray-500 p-4">{session.status === 'closed' ? 'Browser closed. Your report remains available.' : 'Waiting for the first browser frame...'}</div>}
        <div className="p-3 border-t space-y-3">
          {browser?.pending_requests?.map((request) => <article key={request.id} role="alert" className="border border-amber-400 bg-amber-50 p-3 text-xs"><strong>Application request approval</strong><p className="break-all mt-1">{request.method} {request.url}</p><p className="mt-1">This request may submit a login or change application data. Payload: {request.payload_bytes} bytes. Review the browser before allowing it.</p><div className="flex gap-2 mt-2"><button type="button" className={primary} disabled={busy} onClick={() => act(`requests/${request.id}`, { allow: true })}>Allow this request</button><button type="button" className={button} disabled={busy} onClick={() => act(`requests/${request.id}`, { allow: false })}>Deny</button></div></article>)}
          {!!browser?.blocked_origins?.length && <div className="text-xs bg-amber-50 border p-3"><strong>Blocked outside approved origins</strong><p className="break-all mt-1">{browser.blocked_origins.join(', ')}</p><p className="mt-1">If needed for this assessment, create a new session with these exact additional origins approved. They are never added automatically.</p></div>}
          <label className="block text-xs font-semibold">Browser controls (takeover)<select aria-label="Browser control" className="block border p-2 w-full mt-1" value={selectedNode} onChange={(event) => setSelectedNode(event.target.value)}><option value="focused">Select a visible control</option>{browser?.controls?.map((item) => <option key={item.node} value={item.node}>{item.node}: {item.label || item.type || item.tag}</option>)}</select></label>
          <div className="flex gap-2"><button type="button" className={button} disabled={busy || !takeOver || selectedNode === 'focused'} onClick={() => act('input', { op: 'click', node: selectedNode, observation_id: browser.observation_id })}>Click control</button><button type="button" className={button} disabled={busy || !takeOver || selectedNode === 'focused'} onClick={() => act('input', { op: 'press', node: selectedNode, value: 'Enter', observation_id: browser.observation_id })}>Press Enter</button></div>
          <p className="text-[10px] text-gray-500">Authenticated snapshot stream, refreshed about every two seconds. Iframes, downloads, popups, WebSockets and unapproved origins are not used for automated testing. CAPTCHA/MFA requires your input. Ordinary form values are masked in the stream.</p>
        </div>
      </section>
    </div>}
  </div>;
}
