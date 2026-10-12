import { useState } from "react";
import type { SourceLink } from "../api";

/** "Skatīt avotā" links: open the object in the publisher's public system.
 *  A search-page link shows the number to paste there, with a copy button. */
export function SourceLinks({ links, compact }: { links: SourceLink[] | undefined; compact?: boolean }) {
  if (!links || links.length === 0) return null;
  return (
    <span className="srclinks">
      {links.map((l) => (
        <span key={`${l.system}-${l.url}-${l.copy ?? ""}`} className="srclink">
          <a href={l.url} target="_blank" rel="noreferrer" title={l.note ?? `Atvērt ${l.system}`}>
            {l.label ?? (compact ? l.system : `Skatīt avotā: ${l.system}`)} ↗
          </a>
          {l.copy && <CopyButton value={l.copy} note={l.note} />}
        </span>
      ))}
    </span>
  );
}

function CopyButton({ value, note }: { value: string; note?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      window.setTimeout(() => setDone(false), 1500);
    } catch {
      window.prompt("Nokopējiet numuru:", value);
    }
  };
  return (
    <button type="button" className="copy" onClick={copy} title={note ?? "Kopēt meklēšanai"} aria-label={`Kopēt ${value}`}>
      <span className="mono">{value}</span> {done ? "✓ nokopēts" : "⧉ kopēt"}
    </button>
  );
}
