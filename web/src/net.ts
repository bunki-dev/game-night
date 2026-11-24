import { useEffect, useRef, useState } from "react";

export type Phase = "lobby" | "preparing" | "question" | "reveal" | "writing" | "judging" | "results" | "final";

export interface PlayerView {
  id: string;
  name: string;
  color: string;
  score: number;
  connected: boolean;
  last_points: number;
  answered: boolean;
}

export interface RoomState {
  code: string;
  phase: Phase;
  game: "trivia" | "hot_take";
  audience: "family" | "adults";
  round: number;
  total_rounds: number;
  notice: string;
  seconds_left: number | null;
  game_master: string;
  players: PlayerView[];
  question?: { prompt: string; options: string[]; category: string; answer_index?: number; explanation?: string };
  picks?: Record<string, number>;
  prompt?: string;
  answers?: { player_id: string; text: string; score?: number; comment?: string }[];
  my_submission?: { choice?: number; text?: string };
}

export type Hello = { role: "host"; token: string } | { role: "player"; name?: string; token?: string };

export async function createRoom(): Promise<{ code: string; host_token: string; game_master: string }> {
  const res = await fetch("/api/rooms", { method: "POST" });
  if (!res.ok) throw new Error("Couldn't start a game right now. Try again in a minute.");
  return res.json();
}

const playerKey = (code: string) => `gamenight.player.${code}`;

export function savedSeat(code: string): string | null {
  try {
    return localStorage.getItem(playerKey(code));
  } catch {
    return null;
  }
}

function saveSeat(code: string, token: string | null) {
  try {
    if (token) localStorage.setItem(playerKey(code), token);
    else localStorage.removeItem(playerKey(code));
  } catch {
    /* storage unavailable: rejoining after a refresh won't work */
  }
}

/** One live connection to a room, with automatic reconnects. */
export function useRoom(code: string, hello: Hello | null) {
  const [state, setState] = useState<RoomState | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const helloRef = useRef<Hello | null>(hello);
  helloRef.current = hello;

  useEffect(() => {
    if (!hello) return;
    let stopped = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/${code}`);
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        setOnline(true);
        const h = helloRef.current!;
        // After the first join, a phone reconnects with its seat token instead of its name.
        const seat = h.role === "player" ? savedSeat(code) : null;
        ws.send(JSON.stringify(seat ? { role: "player", token: seat } : h));
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "state") {
          setState(msg.state);
        } else if (msg.type === "welcome") {
          setError(null);
          if (msg.role === "player") {
            setMe(msg.player_id);
            saveSeat(code, msg.token);
          }
        } else if (msg.type === "error") {
          setError(msg.message);
          if (msg.fatal) {
            if (helloRef.current?.role === "player") saveSeat(code, null);
            stopped = true;
          }
        }
      };
      ws.onclose = () => {
        setOnline(false);
        if (stopped) return;
        retry = Math.min(retry + 1, 6);
        timer = setTimeout(connect, 400 * 2 ** retry);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [code, hello]);

  const send = (msg: object) => {
    setError(null);
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(msg));
    else setError("Reconnecting… try again in a second.");
  };

  return { state, me, error, online, send };
}
