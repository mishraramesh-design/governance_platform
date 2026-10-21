import { useState } from 'react';
import { toast } from 'sonner';
import { downloadAuthenticated } from '../lib/api';

export function AuthenticatedDownload({ path, filename, children, ...props }) {
  const [busy, setBusy] = useState(false);
  return <button {...props} type="button" disabled={busy} onClick={async () => {
    setBusy(true);
    try { await downloadAuthenticated(path, filename); }
    catch { toast.error('Download unavailable. Check your session and project access.'); }
    finally { setBusy(false); }
  }}>{busy ? 'Downloading…' : children}</button>;
}
