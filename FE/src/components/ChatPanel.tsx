import { useEffect, useRef, useState, type FormEvent } from "react";
import { getLanguageLabel } from "../lib/languages";
import type { RoomChatMessage } from "../types/api";

interface ChatPanelProps {
  messages: RoomChatMessage[];
  selfParticipantId?: string;
  onSend: (text: string) => Promise<boolean>;
  disabled?: boolean;
  error?: string | null;
  isSending?: boolean;
}

export function ChatPanel({
  messages,
  selfParticipantId,
  onSend,
  disabled = false,
  error = null,
  isSending = false,
}: ChatPanelProps) {
  const [inputText, setInputText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = inputText.trim();
    if (!trimmed || disabled || isSending) {
      return;
    }

    const sent = await onSend(trimmed);
    if (sent) {
      setInputText("");
    }
  }

  function formatTime(sentAt: string): string {
    try {
      const date = new Date(sentAt);
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  return (
    <section className="panel chat-panel">
      <div className="panel-header">
        <div>
          <h3>Room Chat</h3>
          <p>Send messages to everyone in the room.</p>
        </div>
        <span className="panel-count">{messages.length}</span>
      </div>

      <div className="chat-message-list" ref={listRef}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p>No messages yet. Start the conversation!</p>
          </div>
        ) : (
          messages.map((message) => {
            const isSelf = message.participant_id === selfParticipantId;
            return (
              <div
                className={`chat-message ${isSelf ? "chat-message-self" : "chat-message-other"}`}
                key={message.message_id}
              >
                <div className="chat-message-header">
                  <strong>{isSelf ? "You" : message.display_name}</strong>
                  {message.sender_language ? (
                    <span className="language-pill chat-lang-pill">
                      {getLanguageLabel(message.sender_language)}
                    </span>
                  ) : null}
                  <span className="chat-timestamp">{formatTime(message.created_at)}</span>
                  {message.delivery_status === "sending" ? (
                    <span className="badge live chat-delivery-badge">Sending</span>
                  ) : null}
                  {message.delivery_status === "failed" ? (
                    <span className="badge warning chat-delivery-badge">Failed</span>
                  ) : null}
                </div>
                <p className="chat-message-text">{message.text}</p>
              </div>
            );
          })
        )}
      </div>

      <form className="chat-input-bar" onSubmit={(event) => void handleSubmit(event)}>
        <input
          className="chat-input"
          type="text"
          placeholder={disabled ? "Chat is unavailable right now" : "Type a message..."}
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          disabled={disabled || isSending}
          maxLength={2000}
          autoComplete="off"
        />
        <button
          className="button-primary chat-send-btn"
          type="submit"
          disabled={disabled || isSending || !inputText.trim()}
        >
          {isSending ? "Sending..." : "Send"}
        </button>
      </form>

      {error ? <div className="inline-error">{error}</div> : null}
    </section>
  );
}
