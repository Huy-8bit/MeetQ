import { describe, expect, it } from "vitest";
import type { LiveRoomDetail, TimelineItem } from "../api/types";
import { diagnoseRoom } from "./diagnosis";
import { formatMs, formatPercent, languagePairLabel } from "./format";

function detail(overrides: Partial<LiveRoomDetail["brse"]> = {}, participants: LiveRoomDetail["participants"] = []): LiveRoomDetail {
  return {
    room: {
      room_id: "rm_x",
      state: "active",
      status: "live",
      room_languages: ["vi", "ja"],
      participants_online: 2,
      participants_total: 2,
      ai_mode: "voice_text",
      brse_enabled: true,
      brse_state: "idle",
      runtime_attached: true,
      created_at: null,
      activated_at: null,
      expires_at: null,
      seconds_left: 600,
      recent_error_count: 0,
      last_error_at: null,
    },
    participants,
    media_source: participants.length ? "livekit" : "unavailable",
    brse: {
      enabled: true,
      ai_mode: "voice_text",
      runtime_attached: true,
      state: "idle",
      current_speaker_id: null,
      current_speaker_name: null,
      queue_depth: 0,
      speakers: [],
      latency: {},
      last_success_at: null,
      last_error: null,
      output_mode_downgrade_reason: null,
      audio_suppressed_reason: null,
      ...overrides,
    },
  };
}

function trace(outcome: string, extra: Partial<TimelineItem> = {}): TimelineItem {
  return {
    event_id: Math.random().toString(36),
    event_type: "relay_trace",
    occurred_at: null,
    room_id: "rm_x",
    utterance_id: null,
    speaker_id: "pt_1",
    speaker_name: "Huy",
    src_lang: "vi",
    target_lang: "ja",
    outcome,
    reason: null,
    issue_code: null,
    severity: null,
    code: null,
    message: null,
    relay_style: "normal",
    stages: [],
    metrics: {},
    source_text: null,
    relay_text: null,
    ...extra,
  };
}

function human(name: string, microphone: string) {
  return {
    participant_id: name,
    display_name: name,
    language: "vi",
    kind: "human",
    is_virtual: false,
    status: "connected",
    ws_connected: true,
    media_connected: true,
    joined_at: null,
    last_seen_at: null,
    is_screen_sharing: false,
    media: { connection: "active", microphone, camera: "off", screen_share: "off" },
  };
}

describe("diagnoseRoom", () => {
  it("reports relay off first", () => {
    const findings = diagnoseRoom(detail({ enabled: false }), []);
    expect(findings.map((finding) => finding.area)).toEqual(["relay_off"]);
  });

  it("points at the runtime and realtime credentials", () => {
    const findings = diagnoseRoom(detail({ runtime_attached: false }), [
      trace("", { event_type: "ai_error", issue_code: "REALTIME_AUTH_FAILED", message: "invalid_api_key" }),
    ]);
    expect(findings[0].area).toBe("runtime");
    expect(findings[1]).toMatchObject({ area: "realtime", severity: "error", title: "OpenAI Realtime rejected the API key" });
  });

  it("flags rooms where no microphone is live", () => {
    const findings = diagnoseRoom(detail({}, [human("Huy", "muted"), human("Kenji", "off")]), []);
    expect(findings.find((finding) => finding.area === "participant")?.title).toBe("No microphone is live");
  });

  it("explains filtered speech and overlap", () => {
    const filtered = diagnoseRoom(detail(), [trace("source_rejected"), trace("source_rejected"), trace("stt_empty"), trace("delivered")]);
    expect(filtered.some((finding) => finding.area === "filtering")).toBe(true);

    const overlap = diagnoseRoom(detail({ queue_depth: 3 }), [trace("delivered")]);
    expect(overlap.some((finding) => finding.area === "overlap")).toBe(true);
  });

  it("reports late relays and missing AI voice", () => {
    const findings = diagnoseRoom(detail(), [
      trace("relay_dropped", { issue_code: "RELAY_TOO_LATE" }),
      trace("delivered", { issue_code: "TTS_NO_AUDIO" }),
    ]);
    const areas = findings.map((finding) => finding.area);
    expect(areas).toContain("delivery");
    expect(areas).toContain("tts");
  });

  it("says relay is healthy when recent utterances were delivered", () => {
    const findings = diagnoseRoom(detail(), [trace("delivered"), trace("delivered"), trace("source_rejected")]);
    expect(findings).toEqual([expect.objectContaining({ area: "healthy", severity: "ok" })]);
  });
});

describe("format helpers", () => {
  it("formats latency, percentages and language pairs", () => {
    expect(formatMs(620)).toBe("620 ms");
    expect(formatMs(1920)).toBe("1.92 s");
    expect(formatMs(null)).toBe("—");
    expect(formatPercent(0.1234)).toBe("12%");
    expect(formatPercent(0.034)).toBe("3.4%");
    expect(languagePairLabel("vi>ja")).toBe("VI → JA");
  });
});
