import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useRoom, type RoomState } from "./net";
import { qrMatrix } from "./qr";
import { Countdown, Suit, Token, useRemoteNavigation } from "./ui";

const TOPICS = ["general knowledge", "sport", "Australia", "space", "animals", "food", "science", "geography", "history", "music"];

export function Tv({ code, token }: { code: string; token: string }) {
  const hello = useMemo(() => ({ role: "host" as const, token }), [token]);
  const { state, error, send, online } = useRoom(code, hello);
  useRemoteNavigation();

  if (!state) {
    return (
      <main className="tv tv-wait">
        <p className="big-note">{error ?? "Setting the table…"}</p>
      </main>
    );
  }
  const answering = state.phase === "question" || state.phase === "writing";
  return (
    <main className="tv">
      <header className="tv-head">
        <span className="logo" aria-label="Game Night">
          Game <em>Night</em>
        </span>
        {state.phase !== "lobby" && state.total_rounds > 0 && state.phase !== "final" && (
          <span className="round-chip">
            {state.game === "trivia" ? "Trivia" : "Hot Take"}: round {state.round} of {state.total_rounds}
          </span>
        )}
        <JoinTicket code={state.code} compact={state.phase !== "lobby"} />
      </header>
      {!online && <p className="banner">Reconnecting to the game server…</p>}
      {error && <p className="banner banner-error">{error}</p>}
      <Stage state={state} send={send} />
      {state.phase !== "final" && (
      <footer className="table-edge">
        {state.players.map((p) => (
          <div key={p.id} className="seat">
            <Token p={{ ...p, answered: answering && p.answered }} />
            <span className="seat-score">{p.score.toLocaleString()}</span>
          </div>
        ))}
        {state.players.length === 0 && <p className="seat-empty">Seats are open. Grab your phone.</p>}
      </footer>
      )}
    </main>
  );
}

function JoinTicket({ code, compact }: { code: string; compact: boolean }) {
  const url = `${location.host}`;
  const joinUrl = `${location.origin}${location.pathname}#/play/${code}`;
  return (
    <div className={`ticket${compact ? " ticket-compact" : ""}`}>
      {!compact && <QrCode text={joinUrl} />}
      <div className="ticket-text">
        {!compact && <span className="ticket-label">Scan, or go to</span>}
        {!compact && <span className="ticket-url">{url}</span>}
        <span className="ticket-code" aria-label={`Room code ${code.split("").join(" ")}`}>
          {code}
        </span>
      </div>
    </div>
  );
}

function QrCode({ text }: { text: string }) {
  const matrix = useMemo(() => qrMatrix(text), [text]);
  const n = matrix.length + 8; // 4-module quiet zone on each side
  let d = "";
  matrix.forEach((row, y) =>
    row.forEach((dark, x) => {
      if (dark) d += `M${x + 4} ${y + 4}h1v1h-1z`;
    }),
  );
  return (
    <svg className="ticket-qr" viewBox={`0 0 ${n} ${n}`} role="img" aria-label="QR code to join this game">
      <rect width={n} height={n} fill="#fff" />
      <path d={d} fill="#1d1d1b" shapeRendering="crispEdges" />
    </svg>
  );
}

function Stage({ state, send }: { state: RoomState; send: (m: object) => void }) {
  switch (state.phase) {
    case "lobby":
      return <Lobby state={state} send={send} />;
    case "preparing":
    case "judging":
      return (
        <section className="stage stage-center">
          <div className="shuffle" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <p className="big-note">{state.notice || "One moment…"}</p>
        </section>
      );
    case "question":
    case "reveal":
      return <QuestionStage state={state} send={send} />;
    case "writing":
      return (
        <section className="stage">
          <Countdown seconds={state.seconds_left} total={60} />
          <article className="card card-prompt">
            <p className="card-kicker">Finish this</p>
            <h1>{state.prompt}</h1>
          </article>
          <p className="big-note">
            {state.players.filter((p) => p.answered).length} of {state.players.length} answers in. Write yours on your
            phone.
          </p>
          <NextButton send={send} label="Close answers" />
        </section>
      );
    case "results":
      return (
        <section className="stage">
          <article className="card card-prompt card-small">
            <h1>{state.prompt}</h1>
          </article>
          <ol className="verdicts">
            {state.answers?.map((a, i) => {
              const p = state.players.find((x) => x.id === a.player_id);
              return (
                <li key={a.player_id} className={i === 0 ? "verdict verdict-top" : "verdict"} style={{ "--tilt": `${(i % 3) - 1}deg` } as CSSProperties}>
                  <p className="verdict-text">“{a.text}”</p>
                  <p className="verdict-who">
                    {p && <span className="dot" style={{ background: p.color }} />}
                    {p?.name ?? "Someone"}
                    <span className="verdict-score">{a.score}/10</span>
                  </p>
                  {a.comment && <p className="verdict-comment">{a.comment}</p>}
                </li>
              );
            })}
          </ol>
          <NextButton send={send} label={state.round >= state.total_rounds ? "Final scores" : "Next prompt"} />
        </section>
      );
    case "final":
      return <Final state={state} send={send} />;
  }
}

function Lobby({ state, send }: { state: RoomState; send: (m: object) => void }) {
  const [game, setGame] = useState<"trivia" | "hot_take">(state.game);
  const [topics, setTopics] = useState<string[]>(["general knowledge"]);
  const [custom, setCustom] = useState("");
  const [rounds, setRounds] = useState(8);
  const [audience, setAudience] = useState<"family" | "adults">(state.audience);
  const startRef = useRef<HTMLButtonElement>(null);
  const ai = !state.game_master.startsWith("Offline");

  useEffect(() => startRef.current?.focus(), []);

  const toggle = (t: string) =>
    setTopics((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t].slice(-4)));
  const allTopics = [...topics, ...(custom.trim() ? [custom.trim()] : [])].slice(0, 4);

  return (
    <section className="stage lobby">
      <div className="lobby-pick">
        <h2>Tonight's game</h2>
        <div className="game-boxes">
          <button data-nav className={game === "trivia" ? "game-box is-on" : "game-box"} onClick={() => setGame("trivia")}>
            <span className="game-box-title">Trivia</span>
            <span className="game-box-sub">Four answers, one's right. Fast fingers score more.</span>
          </button>
          <button data-nav className={game === "hot_take" ? "game-box is-on" : "game-box"} onClick={() => setGame("hot_take")}>
            <span className="game-box-title">Hot Take</span>
            <span className="game-box-sub">Finish the prompt. The AI judge picks the best.</span>
          </button>
        </div>

        {game === "trivia" && (
          <>
            <h3>Topics {ai ? "(pick up to four, or type your own)" : "(up to four)"}</h3>
            <div className="chips">
              {TOPICS.map((t) => (
                <button key={t} data-nav className={topics.includes(t) ? "chip is-on" : "chip"} onClick={() => toggle(t)}>
                  {t}
                </button>
              ))}
            </div>
            {ai && (
              <input
                data-nav
                className="topic-input"
                value={custom}
                maxLength={30}
                onChange={(e) => setCustom(e.target.value)}
                placeholder="Your own topic, e.g. 90s cartoons"
                aria-label="Your own topic"
              />
            )}
          </>
        )}

        <div className="settings-row">
          <span>Rounds</span>
          {[5, 8, 12].map((n) => (
            <button key={n} data-nav className={rounds === n ? "chip is-on" : "chip"} onClick={() => setRounds(n)}>
              {n}
            </button>
          ))}
          <span className="settings-gap">Crowd</span>
          {(["family", "adults"] as const).map((a) => (
            <button key={a} data-nav className={audience === a ? "chip is-on" : "chip"} onClick={() => setAudience(a)}>
              {a === "family" ? "Family" : "Adults"}
            </button>
          ))}
        </div>

        <button
          ref={startRef}
          data-nav
          className="start"
          disabled={state.players.length < (game === "hot_take" ? 2 : 1)}
          onClick={() => send({ type: "start", game, rounds, topics: allTopics, audience })}
        >
          {state.players.length < (game === "hot_take" ? 2 : 1)
            ? game === "hot_take"
              ? "Hot Take needs two players"
              : "Waiting for players"
            : "Deal me in"}
        </button>
        {state.notice && <p className="notice">{state.notice}</p>}
        <p className="fine">Game master: {state.game_master}</p>
      </div>
    </section>
  );
}

function QuestionStage({ state, send }: { state: RoomState; send: (m: object) => void }) {
  const q = state.question!;
  const reveal = state.phase === "reveal";
  return (
    <section className="stage">
      {!reveal && <Countdown seconds={state.seconds_left} total={20} />}
      <article className="card">
        <p className="card-kicker">{q.category}</p>
        <h1>{q.prompt}</h1>
      </article>
      <ul className="options">
        {q.options.map((o, i) => {
          const correct = reveal && q.answer_index === i;
          const pickers = reveal ? state.players.filter((p) => state.picks?.[p.id] === i) : [];
          return (
            <li key={i} className={`option${reveal ? (correct ? " is-right" : " is-wrong") : ""}`}>
              <Suit i={i} size={48} />
              <span className="option-text">{o}</span>
              {pickers.length > 0 && (
                <span className="option-pickers">
                  {pickers.map((p) => (
                    <span key={p.id} className="dot" style={{ background: p.color }} title={p.name} />
                  ))}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {reveal && q.explanation && <p className="explain">{q.explanation}</p>}
      {reveal ? (
        <NextButton send={send} label={state.round >= state.total_rounds ? "Final scores" : "Next question"} />
      ) : (
        <p className="big-note">
          {state.players.filter((p) => p.answered).length} of {state.players.length} locked in
        </p>
      )}
    </section>
  );
}

function Final({ state, send }: { state: RoomState; send: (m: object) => void }) {
  const [first, second, third] = state.players;
  return (
    <section className="stage stage-center">
      <h1 className="final-title">{first ? `${first.name} takes the night` : "Game over"}</h1>
      <div className="podium">
        {[second, first, third].map((p, i) =>
          p ? (
            <div key={p.id} className={`step step-${[2, 1, 3][i]}`}>
              <Token p={{ ...p, answered: false }} big />
              <span className="step-score">{p.score.toLocaleString()}</span>
              <span className="step-block">{[2, 1, 3][i]}</span>
            </div>
          ) : (
            <div key={i} className="step step-empty" />
          ),
        )}
      </div>
      <NextButton send={send} label="Another round" type="lobby" />
    </section>
  );
}

function NextButton({ send, label, type = "next" }: { send: (m: object) => void; label: string; type?: string }) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => ref.current?.focus(), [label]);
  return (
    <button ref={ref} data-nav className="next" onClick={() => send({ type })}>
      {label}
    </button>
  );
}
