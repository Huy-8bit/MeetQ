import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { getLanguageLabel } from "../lib/languages";
import { animateLatestItem } from "../lib/motion";
import { useTextAnimationRoot } from "../lib/textAnimations";
import type { ChatTranslationMode, MeetingLanguage, RoomChatMessage } from "../types/api";
import { MotionButton } from "./MotionButton";

const TRANSLATION_MODE_STORAGE_KEY = "brseai_chat_translation_mode";

function loadStoredTranslationMode(): ChatTranslationMode {
  try {
    const stored = localStorage.getItem(TRANSLATION_MODE_STORAGE_KEY);
    if (stored === "translate" || stored === "original_only") {
      return stored;
    }
  } catch {
    // localStorage unavailable
  }
  return "original_only";
}

function saveTranslationMode(mode: ChatTranslationMode): void {
  try {
    localStorage.setItem(TRANSLATION_MODE_STORAGE_KEY, mode);
  } catch {
    // ignore
  }
}

interface ChatPanelProps {
  messages: RoomChatMessage[];
  selfParticipantId?: string;
  onSend: (text: string, translationMode: ChatTranslationMode) => Promise<boolean>;
  disabled?: boolean;
  error?: string | null;
  isSending?: boolean;
  embedded?: boolean;
  meetingLanguages?: MeetingLanguage[];
}

export function ChatPanel({
  messages,
  selfParticipantId,
  onSend,
  disabled = false,
  error = null,
  isSending = false,
  embedded = false,
  meetingLanguages,
}: ChatPanelProps) {
  const [inputText, setInputText] = useState("");
  const [translationMode, setTranslationMode] = useState<ChatTranslationMode>(
    loadStoredTranslationMode,
  );
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const latestMessageId = messages[messages.length - 1]?.message_id ?? null;
  // Only useful when room has a 2-lang pair and translation can be meaningful.
  const canTranslate = !meetingLanguages || meetingLanguages.length >= 2;
  const textMotionRef = useTextAnimationRoot<HTMLElement>({
    dependencies: [embedded, messages.length === 0, canTranslate],
  });

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length]);

  useEffect(() => {
    const animation = animateLatestItem(listRef.current);
    return () => animation?.pause?.();
  }, [latestMessageId]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) {
      return;
    }
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [inputText]);

  function handleModeChange(mode: ChatTranslationMode): void {
    setTranslationMode(mode);
    saveTranslationMode(mode);
  }

  async function submitMessage() {
    const trimmed = inputText.trim();
    if (!trimmed || disabled || isSending) {
      return;
    }

    const sent = await onSend(trimmed, translationMode);
    if (sent) {
      setInputText("");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitMessage();
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    void submitMessage();
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
    <section className={embedded ? "chat-panel panel-section" : "panel chat-panel"} ref={textMotionRef}>
      <div className="panel-header chat-intro">
        <div>
          <h3 data-text-animate="fade">Room Chat</h3>
          <p data-text-animate="fade">Send messages to everyone in the room.</p>
        </div>
        <span className="panel-count" data-text-animate="fade">{messages.length}</span>
      </div>

      <div
        className={`chat-message-list ${messages.length === 0 ? "chat-message-list-empty" : ""}`}
        ref={listRef}
      >
        {messages.length === 0 ? (
          <div className="chat-empty panel-empty-state">
            <span className="panel-empty-kicker" data-text-animate="highlight">Chat</span>
            <strong data-text-animate="fade">No messages yet</strong>
            <p data-text-animate="fade">Chat notes for this room will appear here.</p>
          </div>
        ) : (
          messages.map((message) => {
            const isSelf = message.participant_id === selfParticipantId;
            const hasTranslation =
              message.translation_mode === "translate" &&
              message.translations != null &&
              message.translations.length > 0;
            const isPendingTranslation =
              message.translation_mode === "translate" &&
              message.delivery_status === "sending";

            return (
              <div
                className={`chat-message ${isSelf ? "chat-message-self" : "chat-message-other"}`}
                key={message.message_id}
                data-motion-latest={message.message_id === latestMessageId ? "true" : undefined}
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

                {hasTranslation
                  ? message.translations!.map((t) => (
                      <div className="chat-translation-block" key={t.language}>
                        <span className="chat-translation-label">
                          Translated · {getLanguageLabel(t.language)}
                        </span>
                        <p className="chat-translation-text">{t.text}</p>
                      </div>
                    ))
                  : null}

                {isPendingTranslation && !hasTranslation ? (
                  <div className="chat-translation-block chat-translation-pending">
                    <span className="chat-translation-label">Translating…</span>
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>

      <div className="chat-composer">
        {canTranslate ? (
          <div className="chat-mode-bar" aria-label="Chat send mode">
            <MotionButton
              type="button"
              className={`chat-mode-btn ${translationMode === "original_only" ? "chat-mode-btn-active" : ""}`}
              onClick={() => handleModeChange("original_only")}
              disabled={disabled}
              title="Send without translation"
              data-text-animate="cta"
            >
              Original
            </MotionButton>
            <MotionButton
              type="button"
              className={`chat-mode-btn ${translationMode === "translate" ? "chat-mode-btn-active" : ""}`}
              onClick={() => handleModeChange("translate")}
              disabled={disabled}
              title="Send with translation"
              data-text-animate="cta"
            >
              + Translate
            </MotionButton>
          </div>
        ) : null}

        <form className="chat-input-bar" onSubmit={(event) => void handleSubmit(event)}>
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder={disabled ? "Chat is unavailable right now" : "Type a message..."}
            value={inputText}
            onChange={(event) => setInputText(event.target.value)}
            onKeyDown={handleInputKeyDown}
            disabled={disabled || isSending}
            maxLength={2000}
            rows={1}
          />
          <MotionButton
            className="button-primary chat-send-btn"
            type="submit"
            disabled={disabled || isSending || !inputText.trim()}
            attentionKey={inputText.trim() ? "chat-ready" : null}
            data-text-animate="cta"
          >
            {isSending ? "Sending..." : "Send"}
          </MotionButton>
        </form>

        {error ? <div className="inline-error">{error}</div> : null}
      </div>
    </section>
  );
}
