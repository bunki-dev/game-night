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
      if (state.game === "emoji") {
        if (!state.my_submission?.text) return <Note title="Too slow!" body={`It was ${state.answer}.`} />;
        return state.my_submission.correct ? (
          <Note title={`+${mine.last_points}`} body={`${state.answer}. Nailed it.`} tone="good" />
        ) : (
          <Note title="Not quite." body={`It was ${state.answer}.`} />
        );
      }
      const right = state.question?.answer_index === state.my_submission?.choice;
      if (state.my_submission?.choice == null) return <Note title="Too slow!" body="No answer this round." />;
      return right ? (
        <Note title={`+${mine.last_points}`} body="Spot on." tone="good" />
      ) : (
        <Note title="Not this time." body={`It was ${state.question?.options[state.question.answer_index ?? 0]}.`} />
      );
    }
    case "writing":
      if (state.game === "emoji") {
        if (state.my_submission?.text) return <Note title="Locked in." body={`“${state.my_submission.text}”. Eyes on the TV.`} />;
        return (
          <form
            className="write"
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim()) send({ type: "answer", text: draft.trim() });
            }}
          >
            <p className="write-emoji">{state.emoji?.emojis}</p>
            <p className="write-prompt">Which {state.emoji?.category} is this? One guess.</p>
            <input value={draft} maxLength={60} onChange={(e) => setDraft(e.target.value)} placeholder="Type your guess" autoFocus />
            <button type="submit" disabled={!draft.trim()}>
              Lock it in
            </button>
          </form>
        );
      }
      return (
        <form
          className="write"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) send({ type: "answer", text: draft.trim() });
          }}
        >
          <p className="write-prompt">{state.prompt}</p>
          <textarea
            value={draft}
            maxLength={state.game === "fake_out" ? 60 : 120}
            rows={state.game === "fake_out" ? 2 : 3}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={state.game === "fake_out" ? "A believable fake answer" : "Make the room laugh"}
          />
          <button type="submit" disabled={!draft.trim()}>
            {state.my_submission?.text ? "Update answer" : "Send it"}
          </button>
          {state.my_submission?.text && <p className="write-sent">Sent. You can still change it.</p>}
        </form>
      );
    case "voting": {
      if (state.my_submission?.vote) return <Note title="Voted." body="Watch the TV for the reveal." />;
      if (state.game === "most_likely")
        return (
          <div className="vote-list">
            <p className="write-prompt">{state.prompt}</p>
            {state.players
              .filter((p) => p.id !== me)
              .map((p) => (
                <button key={p.id} className="vote-btn" style={{ "--c": p.color } as CSSProperties} onClick={() => send({ type: "answer", vote: p.id })}>
                  <span className="dot" style={{ background: p.color }} />
                  {p.name}
                </button>
              ))}
          </div>
        );
      return (
        <div className="vote-list">
          <p className="write-prompt">Which is the real answer?</p>
          {state.options?.map((o) => (
            <button key={o.key} className="vote-btn" disabled={o.mine} onClick={() => send({ type: "answer", vote: o.key })}>
              {o.text}
              {o.mine && <small> (yours)</small>}
            </button>
          ))}
        </div>
      );
    }
    case "judging":
      return <Note title="The judge is reading…" body="No bribes accepted." />;
    case "results": {
      if (state.game === "fake_out") {
        const fooled = state.cards?.filter((c) => c.authors.includes(me)).flatMap((c) => c.voters).length ?? 0;
        const found = state.cards?.some((c) => c.truth && c.voters.includes(me));
        return (
          <Note
            title={mine.last_points ? `+${mine.last_points}` : "No points"}
            body={`${found ? "You found the truth." : `It was “${state.answer}”.`} ${fooled ? `You fooled ${fooled}.` : ""}`}
            tone={mine.last_points ? "good" : undefined}
          />
        );
      }
      if (state.game === "most_likely") {
        const votes = state.tally?.find((t) => t.player_id === me)?.voters.length ?? 0;
        return (
          <Note
            title={mine.last_points ? `+${mine.last_points}` : "Against the crowd"}
            body={`${votes} ${votes === 1 ? "person" : "people"} voted for you.`}
            tone={mine.last_points ? "good" : undefined}
          />
        );
      }
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
