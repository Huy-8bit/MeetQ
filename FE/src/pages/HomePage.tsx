import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { extractRoomId } from "../lib/rooms";

export function HomePage() {
  const navigate = useNavigate();
  const [roomInput, setRoomInput] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreateRoom() {
    setCreating(true);
    setError(null);

    try {
      const response = await api.createRoom();
      navigate(`/rooms/${response.room.room_id}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not create room. Check backend connectivity.",
      );
    } finally {
      setCreating(false);
    }
  }

  function handleJoinExisting() {
    const roomId = extractRoomId(roomInput);
    if (!roomId) {
      setError("Enter a valid room id or a /rooms/{room_id} link.");
      return;
    }

    setError(null);
    navigate(`/rooms/${roomId}`);
  }

  return (
    <main className="home-page">
      <section className="hero-card">
        <div className="hero-copy">
          <span className="eyebrow">brseAI Meeting Platform</span>
          <h1>Realtime multilingual meetings without a separate interpreter.</h1>
          <p>
            Create a room, invite participants by link, and let each person hear
            translated audio routed to their own language.
          </p>

          <div className="hero-pills">
            <span>Video + audio</span>
            <span>VI / EN / JA</span>
            <span>Transcript streaming</span>
          </div>
        </div>

        <div className="hero-actions panel">
          <h2>Start a room</h2>
          <p>Create an instant room or jump into an existing one.</p>

          <button
            className="button-primary"
            type="button"
            onClick={() => {
              void handleCreateRoom();
            }}
            disabled={creating}
          >
            {creating ? "Creating..." : "Create Room"}
          </button>

          <div className="divider">
            <span>or</span>
          </div>

          <label className="field">
            <span>Join existing room</span>
            <input
              value={roomInput}
              onChange={(event) => setRoomInput(event.target.value)}
              placeholder="rm_... or room link"
            />
          </label>

          <button className="button-secondary" type="button" onClick={handleJoinExisting}>
            Open Room
          </button>

          {error ? <div className="inline-error">{error}</div> : null}
        </div>
      </section>
    </main>
  );
}
