import { useEffect, useState, type FormEvent } from "react";
import { createRoom } from "./net";
import { Phone } from "./Phone";
import { Tv } from "./Tv";

// Routes live in the hash so the same static page works on any host:
//   #/tv/CODE  the shared screen    #/play/CODE  a phone
function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

const hostKey = (code: string) => `gamenight.host.${code}`;

export default function App() {
  const hash = useHash();
  const [, screen, code] = hash.match(/^#\/(tv|play)\/([A-Za-z]{4})$/) ?? [];

  if (screen === "tv" && code) {
    const token = sessionStorage.getItem(hostKey(code.toUpperCase()));
    if (token) return <Tv code={code.toUpperCase()} token={token} />;
    location.hash = "";
  }
  if (screen === "play" && code) return <Phone code={code.toUpperCase()} />;
  return <Landing />;
}

function Landing() {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function host() {
    setBusy(true);
    setError(null);
    try {
      const room = await createRoom();
      sessionStorage.setItem(hostKey(room.code), room.host_token);
      location.hash = `#/tv/${room.code}`;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function join(e: FormEvent) {
    e.preventDefault();
    if (/^[A-Za-z]{4}$/.test(code)) location.hash = `#/play/${code.toUpperCase()}`;
  }

  return (
    <main className="landing">
      <h1 className="logo logo-big">
        Game <em>Night</em>
      </h1>
      <p className="landing-sub">Party games on the big screen. Everyone plays from their phone.</p>
      <div className="landing-split">
        <section className="landing-card">
          <h2>On the TV or laptop</h2>
          <p>Open this page on the screen everyone can see.</p>
          <button data-nav className="start" onClick={host} disabled={busy}>
            {busy ? "Setting up…" : "Host a game here"}
          </button>
        </section>
        <section className="landing-card">
          <h2>On your phone</h2>
          <form onSubmit={join}>
            <label htmlFor="code">Room code from the TV</label>
            <input
              id="code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/[^A-Za-z]/g, "").slice(0, 4).toUpperCase())}
              placeholder="ABCD"
              autoCapitalize="characters"
              inputMode="text"
              className="code-input"
            />
            <button type="submit" className="start" disabled={code.length !== 4}>
              Join
            </button>
          </form>
        </section>
      </div>
      {error && <p className="banner banner-error">{error}</p>}
    </main>
  );
}
