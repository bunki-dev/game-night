import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { savedSeat, useRoom, type Hello, type RoomState } from "./net";
import { SUITS, Suit } from "./ui";

export function Phone({ code }: { code: string }) {
  const [name, setName] = useState("");
  const [hello, setHello] = useState<Hello | null>(() => (savedSeat(code) ? { role: "player" } : null));
  const { state, me, error, send, online } = useRoom(code, hello);
  const mine = state?.players.find((p) => p.id === me);

  // A fatal error (room gone, name taken) sends you back to the name form.
  useEffect(() => {
    if (error && !me && hello) setHello(null);
  }, [error, me, hello]);

  if (!hello || !mine || !state) {
    const join = (e: FormEvent) => {
      e.preventDefault();
      if (name.trim()) setHello({ role: "player", name: name.trim() });
    };
    return (
      <main className="phone phone-join">
        <p className="phone-code">Room {code}</p>
        <form onSubmit={join} className="join-form">
          <label htmlFor="name">Your name</label>
          <input
            id="name"
            value={name}
            maxLength={14}
            autoComplete="nickname"
            onChange={(e) => setName(e.target.value)}
            placeholder="What should the TV call you?"
          />
          <button type="submit" disabled={!name.trim() || (!!hello && !error)}>
            {hello && !error ? "Joining…" : "Take a seat"}
          </button>
          {error && <p className="phone-error">{error}</p>}
        </form>
      </main>
    );
  }

  return (
    <main className="phone" style={{ "--me": mine.color } as CSSProperties}>
      <header className="phone-head">
        <span className="phone-me">
          <span className="dot" style={{ background: mine.color }} />
          {mine.name}
        </span>
        <span className="phone-score">{mine.score.toLocaleString()} pts</span>
      </header>
      {!online && <p className="banner">Reconnecting…</p>}
      {error && <p className="phone-error">{error}</p>}
      <Controller state={state} me={me!} send={send} />
    </main>
  );
}

function Controller({ state, me, send }: { state: RoomState; me: string; send: (m: object) => void }) {
  const mine = state.players.find((p) => p.id === me)!;
  const [draft, setDraft] = useState(state.my_submission?.text ?? "");
  useEffect(() => setDraft(state.my_submission?.text ?? ""), [state.round, state.phase]); // eslint-disable-line

  switch (state.phase) {
    case "lobby":
      return <Note title="You're in." body="Watch the TV. The host will deal the first game." />;
    case "preparing":
      return <Note title="Shuffling…" body="The game master is writing tonight's questions." />;
    case "question": {
      const picked = state.my_submission?.choice;
      if (picked != null) return <Note title="Locked in." body="Eyes on the TV." suit={picked} />;
      return (
        <div className="pad">
          {state.question!.options.map((o, i) => (
            <button key={i} className={`pad-btn pad-${SUITS[i].name}`} onClick={() => send({ type: "answer", choice: i })}>
              <Suit i={i} size={56} />
              <span>{o}</span>
            </button>
          ))}
        </div>
      );
    }
    case "reveal": {
      const right = state.question?.answer_index === state.my_submission?.choice;
      if (state.my_submission?.choice == null) return <Note title="Too slow!" body="No answer this round." />;
      return right ? (
        <Note title={`+${mine.last_points}`} body="Spot on." tone="good" />
      ) : (
        <Note title="Not this time." body={`It was ${state.question?.options[state.question.answer_index ?? 0]}.`} />
      );
    }
    case "writing":
      return (
        <form
          className="write"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) send({ type: "answer", text: draft.trim() });
          }}
        >
          <p className="write-prompt">{state.prompt}</p>
          <textarea value={draft} maxLength={120} rows={3} onChange={(e) => setDraft(e.target.value)} placeholder="Make the room laugh" />
          <button type="submit" disabled={!draft.trim()}>
            {state.my_submission?.text ? "Update answer" : "Send it"}
          </button>
          {state.my_submission?.text && <p className="write-sent">Sent. You can still change it.</p>}
        </form>
      );
    case "judging":
      return <Note title="The judge is reading…" body="No bribes accepted." />;
    case "results": {
      const mineAns = state.answers?.find((a) => a.player_id === me);
      return mineAns ? (
        <Note title={`${mineAns.score}/10`} body={mineAns.comment ?? ""} tone={mineAns.score! >= 7 ? "good" : undefined} />
      ) : (
        <Note title="No answer" body="Get one in next round." />
      );
    }
    case "final": {
      const rank = state.players.findIndex((p) => p.id === me) + 1;
      return <Note title={rank === 1 ? "You won!" : `You came ${ordinal(rank)}`} body={`${mine.score.toLocaleString()} points`} tone={rank === 1 ? "good" : undefined} />;
    }
  }
}

function Note({ title, body, tone, suit }: { title: string; body: string; tone?: "good"; suit?: number }) {
  return (
    <section className={`note${tone ? ` note-${tone}` : ""}`}>
      {suit != null && <Suit i={suit} size={72} />}
      <h1>{title}</h1>
      <p>{body}</p>
    </section>
  );
}

function ordinal(n: number) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
