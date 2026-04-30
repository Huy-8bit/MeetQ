import { useCallback, useEffect, useRef, useState } from "react";
import { api, getApiBaseUrl } from "../../lib/api";
import type { Language } from "../../types/api";
import type { TranslationTestServerEvent } from "../../types/ws";

export type TranslationTestUIStatus =
  | "idle"
  | "requesting_permission"
  | "connecting"
  | "listening"
  | "translating"
  | "error"
  | "stopped";

export interface TranslationTestItem {
  /** Stable key — based on utterance order */
  id: string;
  sourceText: string;
  translatedText: string;
  isFinal: boolean;
  timestamp: string;
}

export interface TranslationTestState {
  status: TranslationTestUIStatus;
  srcLang: Language;
  tgtLang: Language;
  items: TranslationTestItem[];
  error: string | null;
  sessionId: string | null;
  /** Latest audio URL if backend provides one */
  lastAudioUrl: string | null;
}

const SAMPLE_RATE = 16000;
const CHUNK_DURATION_MS = 20;

export function useTranslationTest(
  initialSrcLang: Language = "vi",
  initialTgtLang: Language = "en",
) {
  const [state, setState] = useState<TranslationTestState>({
    status: "idle",
    srcLang: initialSrcLang,
    tgtLang: initialTgtLang,
    items: [],
    error: null,
    sessionId: null,
    lastAudioUrl: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const stoppedRef = useRef(false);
  // utterance counter for stable item IDs without needing server-assigned IDs
  const utteranceCounterRef = useRef(0);
  // partial item ID currently in flight
  const pendingItemIdRef = useRef<string | null>(null);

  const cleanup = useCallback((keepState = false) => {
    stoppedRef.current = true;

    if (scriptNodeRef.current) {
      scriptNodeRef.current.disconnect();
      scriptNodeRef.current = null;
    }

    if (audioCtxRef.current) {
      void audioCtxRef.current.close().catch(() => undefined);
      audioCtxRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "translation_test.stop" }));
      }
      ws.close(1000, "client stop");
    }

    if (!keepState) {
      utteranceCounterRef.current = 0;
      pendingItemIdRef.current = null;
    }
  }, []);

  const deleteSession = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    sessionIdRef.current = null;
    try {
      await api.deleteTranslationTest(id);
    } catch {
      // best-effort
    }
  }, []);

  const setSrcLang = useCallback((lang: Language) => {
    setState((s) => (s.status === "idle" || s.status === "stopped" ? { ...s, srcLang: lang } : s));
  }, []);

  const setTgtLang = useCallback((lang: Language) => {
    setState((s) => (s.status === "idle" || s.status === "stopped" ? { ...s, tgtLang: lang } : s));
  }, []);

  const stop = useCallback(async () => {
    cleanup(true);
    await deleteSession();
    setState((s) => ({
      ...s,
      status: "stopped",
    }));
  }, [cleanup, deleteSession]);

  const start = useCallback(
    async (srcLang: Language, tgtLang: Language) => {
      cleanup();
      stoppedRef.current = false;
      utteranceCounterRef.current = 0;
      pendingItemIdRef.current = null;

      setState((s) => ({
        ...s,
        status: "requesting_permission",
        srcLang,
        tgtLang,
        items: [],
        error: null,
        sessionId: null,
        lastAudioUrl: null,
      }));

      // 1. Mic permission
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            sampleRate: SAMPLE_RATE,
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
      } catch {
        setState((s) => ({
          ...s,
          status: "error",
          error: "Mic chưa được cấp quyền. Vui lòng cho phép truy cập microphone.",
        }));
        return;
      }

      if (stoppedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      streamRef.current = stream;

      // 2. Create translation test session
      setState((s) => ({ ...s, status: "connecting" }));
      let sessionResp: Awaited<ReturnType<typeof api.createTranslationTest>>;
      try {
        sessionResp = await api.createTranslationTest({ src_lang: srcLang, tgt_lang: tgtLang });
      } catch (err) {
        cleanup();
        setState((s) => ({
          ...s,
          status: "error",
          error:
            err instanceof Error
              ? err.message
              : "Không tạo được translation test session.",
        }));
        return;
      }

      if (stoppedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        try {
          await api.deleteTranslationTest(sessionResp.session_id);
        } catch {}
        return;
      }

      sessionIdRef.current = sessionResp.session_id;
      setState((s) => ({ ...s, sessionId: sessionResp.session_id }));

      // 3. Connect WebSocket
      const wsUrl = resolveWsUrl(sessionResp.websocket.url);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        if (stoppedRef.current) {
          ws.close(1000);
          return;
        }
        setState((s) => ({ ...s, status: "listening" }));
        startAudioCapture(stream, ws);
      });

      ws.addEventListener("message", (ev) => {
        if (stoppedRef.current) return;
        try {
          const event = JSON.parse(ev.data as string) as TranslationTestServerEvent;
          handleServerEvent(event);
        } catch {}
      });

      ws.addEventListener("close", (ev) => {
        if (stoppedRef.current) return;
        if (ev.code !== 1000) {
          cleanup(true);
          setState((s) => ({
            ...s,
            status: "error",
            error: `WebSocket đóng bất ngờ (code ${ev.code}).`,
          }));
        }
      });

      ws.addEventListener("error", () => {
        if (stoppedRef.current) return;
        cleanup(true);
        setState((s) => ({
          ...s,
          status: "error",
          error: "Không kết nối được WebSocket translation test session.",
        }));
      });
    },
    [cleanup],
  );

  function handleServerEvent(event: TranslationTestServerEvent) {
    switch (event.type) {
      case "translation_test.started":
        setState((s) => ({ ...s, status: "listening" }));
        break;

      case "translation_test.partial": {
        const p = event.payload;
        setState((s) => {
          // If there's an in-flight partial item, update it in place
          if (pendingItemIdRef.current) {
            const id = pendingItemIdRef.current;
            return {
              ...s,
              status: "translating",
              items: s.items.map((item) =>
                item.id === id
                  ? {
                      ...item,
                      sourceText: p.source_text,
                      translatedText: p.translated_text,
                      isFinal: false,
                      timestamp: p.timestamp,
                    }
                  : item,
              ),
            };
          }

          // New utterance — create partial item
          utteranceCounterRef.current += 1;
          const newId = `utt-${utteranceCounterRef.current}`;
          pendingItemIdRef.current = newId;
          return {
            ...s,
            status: "translating",
            items: [
              ...s.items,
              {
                id: newId,
                sourceText: p.source_text,
                translatedText: p.translated_text,
                isFinal: false,
                timestamp: p.timestamp,
              },
            ],
          };
        });
        break;
      }

      case "translation_test.final": {
        const f = event.payload;
        setState((s) => {
          const pendingId = pendingItemIdRef.current;
          pendingItemIdRef.current = null;

          const audioUrl = f.audio_url ?? null;

          if (pendingId) {
            return {
              ...s,
              status: "listening",
              lastAudioUrl: audioUrl,
              items: s.items.map((item) =>
                item.id === pendingId
                  ? {
                      ...item,
                      sourceText: f.source_text,
                      translatedText: f.translated_text,
                      isFinal: true,
                      timestamp: f.timestamp,
                    }
                  : item,
              ),
            };
          }

          // Final without preceding partial — append directly
          utteranceCounterRef.current += 1;
          const newId = `utt-${utteranceCounterRef.current}`;
          return {
            ...s,
            status: "listening",
            lastAudioUrl: audioUrl,
            items: [
              ...s.items,
              {
                id: newId,
                sourceText: f.source_text,
                translatedText: f.translated_text,
                isFinal: true,
                timestamp: f.timestamp,
              },
            ],
          };
        });
        break;
      }

      case "translation_test.error":
        cleanup(true);
        setState((s) => ({
          ...s,
          status: "error",
          error: event.payload.message || "Backend báo lỗi translation test.",
        }));
        break;
    }
  }

  function startAudioCapture(stream: MediaStream, ws: WebSocket) {
    const audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    audioCtxRef.current = audioCtx;

    const source = audioCtx.createMediaStreamSource(stream);

    const bufferSize =
      Math.pow(2, Math.round(Math.log2((SAMPLE_RATE * CHUNK_DURATION_MS) / 1000))) || 512;

    const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
    scriptNodeRef.current = scriptNode;
    source.connect(scriptNode);
    scriptNode.connect(audioCtx.destination);

    scriptNode.addEventListener("audioprocess", (ev) => {
      if (stoppedRef.current || ws.readyState !== WebSocket.OPEN) return;
      const float32 = ev.inputBuffer.getChannelData(0);
      const pcm16 = floatToPcm16(float32);
      ws.send(pcm16.buffer);
    });
  }

  useEffect(() => {
    return () => {
      stoppedRef.current = true;
      cleanup();
      void deleteSession();
    };
  }, [cleanup, deleteSession]);

  return { state, start, stop, setSrcLang, setTgtLang };
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function floatToPcm16(float32: Float32Array): Int16Array {
  const pcm = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

function resolveWsUrl(rawUrl: string): string {
  if (/^wss?:\/\//i.test(rawUrl)) return rawUrl;
  const apiBase = new URL(getApiBaseUrl());
  const wsProto = apiBase.protocol === "https:" ? "wss:" : "ws:";
  const base = `${wsProto}//${apiBase.host}`;
  return new URL(rawUrl, base + "/").toString();
}
