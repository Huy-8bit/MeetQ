import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { MessageSquare, SendHorizontal } from "lucide-react";
import { getLanguageLabel } from "../lib/languages";
import type { ChatTranslationMode, MeetingLanguage, RoomChatMessage } from "../types/api";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { SegmentedControl } from "./ui/SegmentedControl";

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
  meetingLanguages,
}: ChatPanelProps) {
  const [inputText, setInputText] = useState("");
  const [translationMode, setTranslationMode] = useState<ChatTranslationMode>(
    loadStoredTranslationMode,
  );
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Only useful when the room has more than one language.
  const canTranslate = !meetingLanguages || meetingLanguages.length >= 2;

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const el = listRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length]);

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
    <section className="chat" aria-label="Room chat">
      <div className="chat-list" ref={listRef} aria-live="polite" aria-relevant="additions">
        {messages.length === 0 ? (
          <EmptyState
            icon={<MessageSquare size={20} />}
            title="No messages yet"
            description="Messages you send here are visible to everyone in the room."
          />
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
              <article
                className={isSelf ? "chat-message is-self" : "chat-message"}
                key={message.message_id}
              >
                <header className="chat-message-meta">
                  <span className="chat-message-author">{isSelf ? "You" : message.display_name}</span>
                  {message.sender_language ? (
                    <span>{getLanguageLabel(message.sender_language)}</span>
                  ) : null}
                  <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
                  {message.delivery_status === "sending" ? (
                    <span className="chat-message-status">Sending…</span>
                  ) : null}
                  {message.delivery_status === "failed" ? (
                    <span className="chat-message-status is-failed">Not sent</span>
                  ) : null}
                </header>

                <p className="chat-message-text">{message.text}</p>

                {hasTranslation
                  ? message.translations!.map((t) => (
                      <div className="chat-translation" key={t.language}>
                        <span className="chat-translation-label">
                          {getLanguageLabel(t.language)}
                        </span>
                        <p>{t.text}</p>
                      </div>
                    ))
                  : null}

                {isPendingTranslation && !hasTranslation ? (
                  <div className="chat-translation">
                    <span className="chat-translation-label">Translating…</span>
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </div>

      <form className="chat-composer" onSubmit={(event) => void handleSubmit(event)}>
        <label className="sr-only" htmlFor="chat-input">Message</label>
        <div className="chat-input-row">
          <textarea
            id="chat-input"
            ref={inputRef}
            className="textarea"
            placeholder={disabled ? "Chat is unavailable right now" : "Message everyone…"}
            value={inputText}
            onChange={(event) => setInputText(event.target.value)}
            onKeyDown={handleInputKeyDown}
            disabled={disabled || isSending}
            maxLength={2000}
            rows={1}
          />
          <Button
            type="submit"
            variant="primary"
            iconOnly
            size="lg"
            loading={isSending}
            icon={<SendHorizontal size={18} />}
            aria-label="Send message"
            disabled={disabled || !inputText.trim()}
          />
        </div>

        {canTranslate ? (
          <div className="chat-composer-options">
            <span className="field-helper" id="chat-mode-label">Send as</span>
            <SegmentedControl
              ariaLabelledBy="chat-mode-label"
              value={translationMode}
              onChange={handleModeChange}
              disabled={disabled}
              options={[
                { value: "original_only", label: "Original", title: "Send without translation" },
                { value: "translate", label: "Translated", title: "Send with translation for other languages" },
              ]}
            />
          </div>
        ) : null}

        {error ? <p className="field-error" role="alert">{error}</p> : null}
      </form>
    </section>
  );
}
