import { useState } from 'react';
import { Button, Mascot, Toggle } from './ui';
import { Drawer } from './Drawer';
import { errorText, setSharing, walkCreds } from '../lib/api';
import { minutesText } from '../lib/format';
import { PERSONA, SHORT } from '../lib/personas';
import type { WalkState } from '../lib/store';
import type { LngLat, Msg, ObstacleKind, RecoveryOption } from '../lib/types';
import './journey.css';

const KINDS: [ObstacleKind, string][] = [
  ['blocked', 'Path blocked'],
  ['construction', 'Construction'],
  ['place_closed', 'Place closed'],
  ['want_detour', 'Want a different way'],
  ['other', 'Other'],
];

/** "Report a problem": the walker tells Wingman Wally what is in the way. Nothing changes until they choose. */
export function ReportSheet({ open, onClose, send, at }: { open: boolean; onClose: () => void; send: (m: Msg) => void; at?: LngLat }) {
  const [kind, setKind] = useState<ObstacleKind | null>(null);
  const [note, setNote] = useState('');
  const [sent, setSent] = useState(false);
  const close = () => { onClose(); setSent(false); setKind(null); setNote(''); };
  const submit = () => {
    if (!kind) return;
    send({ type: 'obstacle.report', kind, ...(note.trim() ? { note: note.trim() } : {}), ...(at ? { lngLat: at } : {}) });
    setSent(true);
  };
  return (
    <Drawer open={open} onClose={close} label="Report a problem" title={<><Mascot agent="rescuer" size={28} alt="" /> Report a problem</>}>
      {sent ? (
        <>
          <p className="lj__p">Sent to {PERSONA.rescuer}. {SHORT.guide} is looking for other ways from here. Your route stays the same unless you choose a new one.</p>
          <Button kind="secondary" block onClick={close}>Back to the walk</Button>
        </>
      ) : (
        <>
          <div className="lj__kinds" role="radiogroup" aria-label="What is the problem">
            {KINDS.map(([k, label]) => (
              <button type="button" key={k} role="radio" aria-checked={kind === k} className={`pref-chip${kind === k ? ' pref-chip--on' : ''}`} onClick={() => setKind(k)}>{label}</button>
            ))}
          </div>
          <label className="lj__note">
            <span className="t-caption">Note (optional)</span>
            <textarea value={note} maxLength={200} rows={2} onChange={(e) => setNote(e.target.value)} placeholder="e.g. sidewalk fenced off at the corner" />
          </label>
          <p className="t-caption lj__p">{at ? 'Your current position is sent with the report.' : 'Your position is not known yet, so the report goes without it.'} Nothing is sent to the city.</p>
          <Button kind="primary" block disabled={!kind} onClick={submit}>Send report</Button>
        </>
      )}
    </Drawer>
  );
}

type Recovery = NonNullable<WalkState['recovery']>;

/** Mission Recovery: the current route next to the options Scoot found. The walker decides; nothing switches by itself. */
export function RecoverySheet({ r, now, send, onDismiss }: { r: Recovery; now: number; send: (m: Msg) => void; onDismiss: () => void }) {
  const expired = r.expiresAt > 0 && now > r.expiresAt;
  const choose = (optionId: string) => send({ type: 'recovery.choose', recoveryId: r.recoveryId, optionId });
  return (
    <Drawer open onClose={onDismiss} label="Mission Recovery" title={<><Mascot agent="rescuer" size={28} state="talking" alt="" /> Mission Recovery</>}>
      <p className="lj__p"><strong>{r.reason}</strong></p>
      {r.explanation && (
        <div className="lj__say">
          <Mascot agent="head" size={24} alt="" />
          <div>
            <p className="lj__p">{r.explanation}</p>
            {r.explainedBy && <span className="t-caption">explained by {r.explainedBy}</span>}
          </div>
        </div>
      )}
      {r.chosen ? (
        <p className="lj__p" role="status">{r.chosen === 'keep' ? 'Keeping your route.' : `Switching… waiting for ${SHORT.guide}'s new plan.`}</p>
      ) : expired ? (
        <>
          <p className="lj__p lj__warn">These options expired. Keep walking your route, or report again for fresh options.</p>
          <Button kind="secondary" block onClick={onDismiss}>Close</Button>
        </>
      ) : (
        <ul className="lj__opts">
          <OptionRow o={r.current} current onPick={() => choose('keep')} />
          {r.options.map((o) => <OptionRow key={o.id} o={o} onPick={() => choose(o.id)} />)}
          {r.options.length === 0 && <li className="t-caption">{SHORT.guide} found no other way from here. Your current route stays.</li>}
        </ul>
      )}
      <p className="t-caption lj__p">Conditions, not a safety rating. Numbers come from the route engine.</p>
    </Drawer>
  );
}

function OptionRow({ o, current, onPick }: { o: RecoveryOption; current?: boolean; onPick: () => void }) {
  return (
    <li className={`lj__opt${current ? ' lj__opt--current' : ''}`}>
      <div className="lj__opt-head">
        <strong>{current ? `Current · ${o.label}` : o.label}</strong>
        {o.avoidsReport ? <span className="st-chip st-chip--ok">avoids your report</span> : <span className="st-chip st-chip--warn">passes your report</span>}
      </div>
      <div className="lj__stats">
        <div><span className="t-mono">{minutesText(o.stats.minutes)}</span><small>to go</small></div>
        <div><span className="t-mono">{o.stats.score}</span><small>score</small></div>
        <div><span className="t-mono">{o.stats.longestEmptyM} m</span><small>longest empty</small></div>
      </div>
      {o.liveEvidence > 0 && <span className="t-caption">{o.liveEvidence} place{o.liveEvidence === 1 ? '' : 's'} with listings checked on request</span>}
      <Button kind={current ? 'secondary' : 'primary'} block onClick={onPick}>{current ? 'Keep my route' : 'Switch to this route'}</Button>
    </li>
  );
}

/** Guardian sharing on or off. Off revokes the link at once; on issues a new link (old links stay dead). */
export function SharingControl({ walkId, active, onChange }: { walkId: string; active: boolean; onChange: (v: boolean) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const link = active ? walkCreds(walkId)?.guardianUrl ?? null : null;
  const shareLink = async () => {
    if (!link) return;
    try {
      if (navigator.share) await navigator.share({ title: 'My walk', text: 'Follow my walk live', url: link });
      else { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 2500); }
    } catch { /* the walker closed the share sheet */ }
  };
  const flip = async (v: boolean) => {
    setBusy(true); setErr(null);
    try {
      const r = await setSharing(walkId, v);
      onChange(r.active);
    } catch (e) {
      setErr(errorText(e, 'Could not change sharing.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="lj__share">
      <div className="lj__share-text">
        <strong>{active ? 'Sharing on' : 'Sharing stopped'}</strong>
        <span className="t-caption">{busy ? 'Updating…' : active ? 'Your guardian link shows your live position.' : 'Your guardian link is revoked. Turning it on makes a new link.'}</span>
        {err && <span className="lj__err" role="alert">{err}</span>}
      </div>
      <Toggle on={active} onChange={(v) => { if (!busy) void flip(v); }} label="Share live location with guardian" />
      {link && <Button kind="secondary" onClick={() => void shareLink()}>{copied ? 'Link copied' : 'Send guardian link'}</Button>}
    </div>
  );
}
