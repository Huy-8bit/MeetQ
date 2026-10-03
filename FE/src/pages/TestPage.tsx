import { useRef } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { CustomSelect, type CustomSelectOption } from "../components/CustomSelect";
import { MicLevelMeter } from "../components/MicLevelMeter";
import { Alert } from "../components/ui/Alert";
import { Badge, type BadgeTone } from "../components/ui/Badge";
import { Button, buttonClassName } from "../components/ui/Button";
import { Field } from "../components/ui/Field";
import { useMicTest } from "../features/test/useMicTest";
import { useTranslationTest } from "../features/test/useTranslationTest";
import { getLanguageLabel, SUPPORTED_MEETING_LANGUAGES } from "../lib/languages";
import type { Language } from "../types/api";

export function TestPage() {
  return (
    <div className="page">
      <header className="page-header">
        <Link to="/" className={buttonClassName({ variant: "ghost", size: "sm", className: "page-back" })}>
          <ArrowLeft size={16} aria-hidden="true" />
          Home
        </Link>
        <h1 className="page-title">Device check</h1>
        <p className="page-description">
          Make sure your microphone works and hear how translation sounds before you join a meeting.
        </p>
      </header>

      <main className="test-grid">
        <MicTestSection />
        <TranslationTestSection />
      </main>
    </div>
  );
}

// ─── Mic Test ─────────────────────────────────────────────────────────────────

function MicTestSection() {
  const { state, start, stop } = useMicTest();
  const isActive =
    state.status === "active" || state.status === "silence" || state.status === "connecting";
  const status = MIC_STATUS[state.status] ?? { label: state.status, tone: "neutral" as BadgeTone };

  return (
    <section className="card" aria-labelledby="mic-test-title">
      <div className="card-body test-card">
        <div className="card-header">
          <div>
            <h2 className="card-title" id="mic-test-title">Microphone</h2>
            <p className="card-description">Check that your mic picks up your voice.</p>
          </div>
          <Badge tone={status.tone} dot>{status.label}</Badge>
        </div>

        {state.error ? <Alert tone="danger">{state.error}</Alert> : null}

        <div className="test-meter">
          <MicLevelMeter level={state.level} peak={state.peak} db={state.db} />
          <p className="field-helper" aria-live="polite">{micFeedbackText(state.status, state.level)}</p>
        </div>

        <div className="test-footer">
          {state.sessionId ? <span className="test-session mono">Session {state.sessionId}</span> : <span />}
          {!isActive ? (
            <Button
              variant="primary"
              onClick={() => void start()}
              loading={state.status === "requesting_permission" || state.status === "connecting"}
            >
              {state.status === "requesting_permission"
                ? "Waiting for permission…"
                : state.status === "connecting"
                ? "Connecting…"
                : "Start mic test"}
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => void stop()}>
              Stop
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

const MIC_STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  idle: { label: "Not started", tone: "neutral" },
  requesting_permission: { label: "Permission", tone: "warning" },
  connecting: { label: "Connecting", tone: "warning" },
  active: { label: "Listening", tone: "success" },
  silence: { label: "Silent", tone: "warning" },
  stopped: { label: "Stopped", tone: "neutral" },
  error: { label: "Error", tone: "danger" },
};

function micFeedbackText(status: string, level: number): string {
  switch (status) {
    case "idle":
      return "Start the test, then say a few words.";
    case "requesting_permission":
      return "Allow microphone access in your browser.";
    case "connecting":
      return "Connecting to the test session…";
    case "active":
      return level > 0.05 ? "We can hear you." : "Waiting for you to speak…";
    case "silence":
      return "No speech detected. Check that the right microphone is selected.";
    case "stopped":
      return "Test stopped.";
    case "error":
      return "Something went wrong. See the details above.";
    default:
      return "";
  }
}

// ─── Translation Test ─────────────────────────────────────────────────────────

function TranslationTestSection() {
  const { state, start, stop, setSrcLang, setTgtLang } = useTranslationTest("vi", "en");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const isRunning =
    state.status === "listening" ||
    state.status === "translating" ||
    state.status === "connecting";

  const canChangeLang = state.status === "idle" || state.status === "stopped";
  const sameLanguage = state.srcLang === state.tgtLang;
  const languageOptions: Array<CustomSelectOption<Language>> = SUPPORTED_MEETING_LANGUAGES.map(
    (language) => ({
      value: language,
      label: getLanguageLabel(language),
    }),
  );
  const status = TRANSLATION_STATUS[state.status] ?? { label: state.status, tone: "neutral" as BadgeTone };

  function handleStart() {
    void start(state.srcLang, state.tgtLang);
  }

  // Play audio if backend provides a URL
  function playAudio(url: string) {
    if (!audioRef.current) return;
    audioRef.current.src = url;
    void audioRef.current.play().catch(() => undefined);
  }

  // Trigger playback when a new audio URL arrives
  const prevAudioUrlRef = useRef<string | null>(null);
  if (
    state.lastAudioUrl &&
    state.lastAudioUrl !== prevAudioUrlRef.current
  ) {
    prevAudioUrlRef.current = state.lastAudioUrl;
    playAudio(state.lastAudioUrl);
  }

  return (
    <section className="card" aria-labelledby="translation-test-title">
      <div className="card-body test-card">
        <div className="card-header">
          <div>
            <h2 className="card-title" id="translation-test-title">Translation</h2>
            <p className="card-description">Speak and watch the live translation.</p>
          </div>
          <Badge tone={status.tone} dot pulse={state.status === "translating"}>{status.label}</Badge>
        </div>

        {state.error ? <Alert tone="danger">{state.error}</Alert> : null}

        <div className="test-languages">
          <Field label="From" htmlFor="test-src-lang">
            <CustomSelect
              id="test-src-lang"
              value={state.srcLang}
              options={languageOptions}
              disabled={!canChangeLang}
              onChange={setSrcLang}
              ariaLabel="From language"
            />
          </Field>
          <ArrowRight className="test-languages-arrow" size={16} aria-hidden="true" />
          <Field label="To" htmlFor="test-tgt-lang">
            <CustomSelect
              id="test-tgt-lang"
              value={state.tgtLang}
              options={languageOptions}
              disabled={!canChangeLang}
              onChange={setTgtLang}
              ariaLabel="To language"
            />
          </Field>
        </div>
        {sameLanguage && canChangeLang ? (
          <p className="field-error">Pick two different languages.</p>
        ) : null}

        <div className="test-transcripts" aria-live="polite">
          <div className="test-transcript">
            <p className="test-transcript-label">{getLanguageLabel(state.srcLang)}</p>
            {state.items.length === 0 ? (
              <p className="text-tertiary">{isRunning ? "Waiting for speech…" : "Nothing yet"}</p>
            ) : (
              state.items.map((item) => (
                <p key={item.id} className={item.isFinal ? undefined : "is-partial"}>
                  {item.sourceText}
                </p>
              ))
            )}
          </div>
          <div className="test-transcript">
            <p className="test-transcript-label">{getLanguageLabel(state.tgtLang)}</p>
            {state.items.length === 0 ? (
              <p className="text-tertiary">{isRunning ? "Waiting for translation…" : "Nothing yet"}</p>
            ) : (
              state.items.map((item) => (
                <p key={item.id} className={item.isFinal ? undefined : "is-partial"}>
                  {item.translatedText || "…"}
                </p>
              ))
            )}
          </div>
        </div>

        {/* Hidden audio element for translated audio playback */}
        <audio ref={audioRef} hidden />

        <div className="test-footer">
          {state.sessionId ? <span className="test-session mono">Session {state.sessionId}</span> : <span />}
          {!isRunning ? (
            <Button
              variant="primary"
              onClick={handleStart}
              loading={state.status === "requesting_permission" || state.status === "connecting"}
              disabled={sameLanguage}
            >
              {state.status === "requesting_permission"
                ? "Waiting for permission…"
                : state.status === "connecting"
                ? "Connecting…"
                : "Start translation test"}
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => void stop()}>
              Stop
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

const TRANSLATION_STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  idle: { label: "Not started", tone: "neutral" },
  requesting_permission: { label: "Permission", tone: "warning" },
  connecting: { label: "Connecting", tone: "warning" },
  listening: { label: "Listening", tone: "success" },
  translating: { label: "Translating", tone: "accent" },
  stopped: { label: "Stopped", tone: "neutral" },
  error: { label: "Error", tone: "danger" },
};
