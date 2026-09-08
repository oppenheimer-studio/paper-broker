import type { SystemEvent } from "./types";

type Props = {
  events: SystemEvent[];
  open: boolean;
  onClose: () => void;
};

export function NotificationsPanel({ events, open, onClose }: Props) {
  if (!open) return null;
  return (
    <div className="notes-panel" role="dialog" aria-label="System notifications">
      <div className="notes-head">
        <div>
          <div className="notes-title">System notifications</div>
          <div className="notes-sub">Ingest, fallbacks, and warehouse events</div>
        </div>
        <button className="icon-btn" type="button" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      {!events.length ? (
        <div className="notes-empty">No system events yet.</div>
      ) : (
        <ul className="notes-list">
          {events.map((e) => (
            <li key={e.id} className={`note note-${e.level}`}>
              <div className="note-top">
                <span className={`note-level ${e.level}`}>{e.level}</span>
                <span className="note-time">{formatTs(e.ts)}</span>
              </div>
              <div className="note-title">{e.title}</div>
              {e.detail ? <div className="note-detail">{e.detail}</div> : null}
              <div className="note-code">
                {e.source} · {e.code}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}
