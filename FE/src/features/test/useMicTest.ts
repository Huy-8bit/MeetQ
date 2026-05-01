import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { resolveGatewayWebSocketUrl } from "../../lib/urls";
import type { MicTestServerEvent } from "../../types/ws";

export type MicTestUIStatus =
  | "idle"
  | "requesting_permission"
  | "connecting"
  | "active"
  | "silence"
  | "stopped"
  | "error";

export interface MicTestState {
  status: MicTestUIStatus;
  /** RMS level 0–1 (server-confirmed when available, local fallback otherwise) */
  level: number;
  /** Peak level 0–1 */
  peak: number;
  /** dB value from server */
  db: number | null;
  error: string | null;
  sessionId: string | null;
}

const INITIAL_STATE: MicTestState = {
  status: "idle",
  level: 0,
  peak: 0,
  db: null,
  error: null,
  sessionId: null,
};

const CHUNK_DURATION_MS = 20;
const SAMPLE_RATE = 16000;
const SILENCE_FEEDBACK_MS = 500;

export function useMicTest() {
  const [state, setState] = useState<MicTestState>(INITIAL_STATE);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const stoppedRef = useRef(false);
  const localSilenceTimerRef = useRef<number | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const cleanup = useCallback((keepState = false) => {
    stoppedRef.current = true;

    if (animFrameRef.current !== null) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }

    if (localSilenceTimerRef.current !== null) {
      clearTimeout(localSilenceTimerRef.current);
      localSilenceTimerRef.current = null;
    }

    if (scriptNodeRef.current) {
      scriptNodeRef.current.disconnect();
      scriptNodeRef.current = null;
    }

    if (analyserRef.current) {
      analyserRef.current.disconnect();
      analyserRef.current = null;
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
        ws.send(JSON.stringify({ type: "mic_test.stop" }));
      }
      ws.close(1000, "client stop");
    }

    if (!keepState) {
      setState((s) => ({ ...s, level: 0, peak: 0, db: null }));
    }
  }, []);

  // Delete session on backend when component unmounts or stop is called
  const deleteSession = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    sessionIdRef.current = null;
    try {
      await api.deleteMicTest(id);
    } catch {
      // best-effort
    }
  }, []);

  const stop = useCallback(async () => {
    cleanup(true);
    await deleteSession();
    setState((s) => ({ ...s, status: "stopped", level: 0, peak: 0, db: null }));
  }, [cleanup, deleteSession]);

  const start = useCallback(async () => {
    cleanup();
    stoppedRef.current = false;

    setState({
      ...INITIAL_STATE,
      status: "requesting_permission",
    });

    // 1. Request mic permission
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
      setState({
        ...INITIAL_STATE,
        status: "error",
        error: "Mic chưa được cấp quyền. Vui lòng cho phép truy cập microphone.",
      });
      return;
    }

    if (stoppedRef.current) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    streamRef.current = stream;

    // 2. Create test session
    setState((s) => ({ ...s, status: "connecting" }));
    let sessionResp: Awaited<ReturnType<typeof api.createMicTest>>;
    try {
      sessionResp = await api.createMicTest();
    } catch (err) {
      cleanup();
      setState({
        ...INITIAL_STATE,
        status: "error",
        error:
          err instanceof Error
            ? err.message
            : "Không tạo được test session. Kiểm tra backend.",
      });
      return;
    }

    if (stoppedRef.current) {
      stream.getTracks().forEach((t) => t.stop());
      try {
        await api.deleteMicTest(sessionResp.session_id);
      } catch {}
      return;
    }

    sessionIdRef.current = sessionResp.session_id;
    setState((s) => ({
      ...s,
      sessionId: sessionResp.session_id,
      status: "connecting",
    }));

    // 3. Connect WebSocket
    const wsUrl = resolveGatewayWebSocketUrl(sessionResp.websocket.url);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.addEventListener("open", () => {
      if (stoppedRef.current) {
        ws.close(1000);
        return;
      }
      setState((s) => ({ ...s, status: "active" }));
      startAudioCapture(stream, ws);
    });

    ws.addEventListener("message", (ev) => {
      if (stoppedRef.current) return;
      try {
        const event = JSON.parse(ev.data as string) as MicTestServerEvent;
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
        error: "Không kết nối được WebSocket test session.",
      }));
    });
  }, [cleanup]);

  function handleServerEvent(event: MicTestServerEvent) {
    switch (event.type) {
      case "mic_test.started":
        setState((s) => ({ ...s, status: "active" }));
        break;

      case "mic_test.level":
        if (localSilenceTimerRef.current !== null) {
          clearTimeout(localSilenceTimerRef.current);
          localSilenceTimerRef.current = null;
        }
        setState((s) => ({
          ...s,
          status: "active",
          level: clamp(event.payload.rms, 0, 1),
          peak: clamp(event.payload.peak, 0, 1),
          db: event.payload.db,
        }));
        break;

      case "mic_test.silence":
        setState((s) => ({ ...s, status: "silence" }));
        break;

      case "mic_test.stopped":
        cleanup(true);
        setState((s) => ({ ...s, status: "stopped", level: 0, peak: 0 }));
        break;

      case "mic_test.error":
        cleanup(true);
        setState((s) => ({
          ...s,
          status: "error",
          error: event.payload.message || "Backend báo lỗi mic test.",
        }));
        break;
    }
  }

  function startAudioCapture(stream: MediaStream, ws: WebSocket) {
    const audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    audioCtxRef.current = audioCtx;

    const source = audioCtx.createMediaStreamSource(stream);

    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyserRef.current = analyser;
    source.connect(analyser);

    const bufferSize =
      Math.pow(2, Math.round(Math.log2((SAMPLE_RATE * CHUNK_DURATION_MS) / 1000))) || 512;

    // ScriptProcessor for binary PCM16 streaming
    const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
    scriptNodeRef.current = scriptNode;
    source.connect(scriptNode);
    scriptNode.connect(audioCtx.destination);

    scriptNode.addEventListener("audioprocess", (ev) => {
      if (stoppedRef.current || ws.readyState !== WebSocket.OPEN) return;

      const float32 = ev.inputBuffer.getChannelData(0);
      const pcm16 = floatToPcm16(float32);
      ws.send(pcm16.buffer);

      // Local RMS fallback (server level events override this)
      const rms = computeRms(float32);
      if (rms < 0.01) {
        if (localSilenceTimerRef.current === null) {
          localSilenceTimerRef.current = window.setTimeout(() => {
            setState((s) =>
              s.status === "active" ? { ...s, status: "silence" } : s,
            );
            localSilenceTimerRef.current = null;
          }, SILENCE_FEEDBACK_MS);
        }
      } else {
        if (localSilenceTimerRef.current !== null) {
          clearTimeout(localSilenceTimerRef.current);
          localSilenceTimerRef.current = null;
        }
        setState((s) => {
          // Only apply local level if server hasn't sent a level event yet
          // (server level events always win — they update status/level directly)
          if (s.status === "active" || s.status === "silence") {
            return { ...s, status: "active", level: clamp(rms * 4, 0, 1) };
          }
          return s;
        });
      }
    });
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stoppedRef.current = true;
      cleanup();
      void deleteSession();
    };
  }, [cleanup, deleteSession]);

  return { state, start, stop };
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function computeRms(buffer: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < buffer.length; i++) {
    sum += buffer[i] * buffer[i];
  }
  return Math.sqrt(sum / buffer.length);
}

function floatToPcm16(float32: Float32Array): Int16Array {
  const pcm = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}
