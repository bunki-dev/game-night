import { useEffect } from "react";
import type { PlayerView } from "./net";

// Answer options are card suits: easy to tell apart across a room, and on the phone.
export const SUITS = [
  { name: "spades", color: "#1d1d1b", path: "M50 8C38 28 14 38 14 60a18 18 0 0 0 30 12L38 92h24l-6-20a18 18 0 0 0 30-12C86 38 62 28 50 8z" },
  { name: "hearts", color: "#d7263d", path: "M50 90C22 68 8 52 8 34a20 20 0 0 1 42-10 20 20 0 0 1 42 10c0 18-14 34-42 56z" },
  { name: "clubs", color: "#1d1d1b", path: "M50 10a17 17 0 0 0-13 28 17 17 0 1 0 6 30L38 92h24l-5-24a17 17 0 1 0 6-30A17 17 0 0 0 50 10z" },
  { name: "diamonds", color: "#d7263d", path: "M50 6 86 50 50 94 14 50z" },
];

export function Suit({ i, size = 40 }: { i: number; size?: number }) {
  const s = SUITS[i];
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} aria-label={s.name} role="img" className="suit">
      <path d={s.path} fill={s.color} />
    </svg>
  );
}

export function Token({ p, big = false }: { p: PlayerView; big?: boolean }) {
  const initials = p.name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <div className={`token${big ? " token-big" : ""}${p.answered ? " is-in" : ""}${p.connected ? "" : " is-away"}`}>
      <span className="token-disc" style={{ background: p.color }} aria-hidden="true">
        {initials}
      </span>
      <span className="token-name">{p.name}</span>
    </div>
  );
}

export function Countdown({ seconds, total }: { seconds: number | null; total: number }) {
  if (seconds == null) return null;
  const frac = Math.max(0, Math.min(1, seconds / total));
  return (
    <div className={`countdown${seconds <= 5 ? " is-low" : ""}`} role="timer" aria-label={`${seconds} seconds left`}>
      <svg viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="22" cy="22" r="19" className="countdown-track" />
        <circle cx="22" cy="22" r="19" className="countdown-fill" style={{ strokeDashoffset: `${(1 - frac) * 119.4}` }} />
      </svg>
      <span>{seconds}</span>
    </div>
  );
}

/** TV remotes send arrow keys and Enter: move focus between [data-nav] controls in reading order. */
export function useRemoteNavigation() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const keys = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
      if (!keys.includes(e.key)) return;
      const tag = (document.activeElement as HTMLElement | null)?.tagName;
      if (tag === "INPUT" && (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
      const items = Array.from(document.querySelectorAll<HTMLElement>("[data-nav]:not([disabled])"));
      if (!items.length) return;
      e.preventDefault();
      const current = items.indexOf(document.activeElement as HTMLElement);
      const step = e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 1;
      const next = current < 0 ? 0 : (current + step + items.length) % items.length;
      items[next].focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
