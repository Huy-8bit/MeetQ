import type { LiveRoomDetail, TimelineItem } from "../api/types";

export type DiagnosisArea =
  | "relay_off"
  | "runtime"
  | "realtime"
  | "participant"
  | "stt"
  | "filtering"
  | "overlap"
  | "translation"
  | "tts"
  | "delivery"
  | "healthy"
  | "no_activity";

export interface Finding {
  area: DiagnosisArea;
  severity: "error" | "warning" | "info" | "ok";
  title: string;
  detail: string;
}

const RECENT_TRACES = 10;

function share(items: TimelineItem[], predicate: (item: TimelineItem) => boolean): number {
  return items.length ? items.filter(predicate).length / items.length : 0;
}

/**
 * Answers "BRSE AI is not translating — where is it failing?" for one live room,
 * using only data the backend reported. Ordered from most to least fundamental.
 */
export function diagnoseRoom(detail: LiveRoomDetail, timeline: TimelineItem[]): Finding[] {
  const findings: Finding[] = [];
  const { room, brse, participants } = detail;

  if (!brse.enabled) {
    return [{ area: "relay_off", severity: "info", title: "AI relay is off", detail: "Someone turned BRSE AI off for this room, or the room was created with AI relay Off." }];
  }
  if (brse.runtime_attached === false) {
    findings.push({
      area: "runtime",
      severity: "error",
      title: "BRSE runtime is not attached",
      detail: "The brain runtime heartbeat does not list this room. Check the interpreter service.",
    });
  }

  const errors = timeline.filter((item) => item.event_type === "ai_error");
  const realtimeError = errors.find((item) =>
    ["REALTIME_AUTH_FAILED", "REALTIME_UNAVAILABLE", "REALTIME_DISCONNECTED"].includes(item.issue_code ?? ""),
  );
  if (realtimeError) {
    findings.push({
      area: "realtime",
      severity: realtimeError.issue_code === "REALTIME_DISCONNECTED" ? "warning" : "error",
      title: realtimeError.issue_code === "REALTIME_AUTH_FAILED" ? "OpenAI Realtime rejected the API key" : "OpenAI Realtime connection problem",
      detail: realtimeError.message ?? "The speaker's realtime session is not connected.",
    });
  }
  const routeError = errors.find((item) => item.issue_code === "ROUTE_CONFIG_ERROR");
  if (routeError) {
    findings.push({ area: "participant", severity: "error", title: "Speaker language does not match the room", detail: routeError.message ?? "" });
  }

  const humans = participants.filter((participant) => !participant.is_virtual && participant.status !== "disconnected");
  if (detail.media_source === "livekit") {
    const silent = humans.filter((participant) => participant.media && participant.media.microphone !== "on");
    const micState = (participant: (typeof humans)[number]) =>
      participant.media?.connection === "not_connected"
        ? "not connected to media"
        : participant.media?.microphone === "muted"
          ? "muted"
          : "no microphone";
    if (silent.length && silent.length === humans.length) {
      findings.push({
        area: "participant",
        severity: "warning",
        title: "No microphone is live",
        detail: `${silent.map((participant) => `${participant.display_name} (${micState(participant)})`).join(", ")} — there is nothing for BRSE AI to translate.`,
      });
    } else if (silent.length) {
      findings.push({
        area: "participant",
        severity: "info",
        title: "Some microphones are muted or missing",
        detail: silent.map((participant) => `${participant.display_name}: ${participant.media?.microphone ?? "unknown"}`).join(" · "),
      });
    }
  }
  if (humans.length === 1 && room.ai_mode !== "captions") {
    findings.push({
      area: "participant",
      severity: "info",
      title: "Only one person is in the room",
      detail: "Relay still runs, but nobody else is listening in another language.",
    });
  }

  const traces = timeline.filter((item) => item.event_type === "relay_trace").slice(0, RECENT_TRACES);
  if (traces.length === 0) {
    if (!findings.length) {
      findings.push({ area: "no_activity", severity: "info", title: "No speech processed yet", detail: "No utterance has reached BRSE AI in this room so far." });
    }
    return findings;
  }

  if (share(traces, (item) => item.outcome === "stt_failed") >= 0.3) {
    findings.push({ area: "stt", severity: "error", title: "Transcription is failing", detail: "Recent utterances failed at STT." });
  }
  if (share(traces, (item) => item.outcome === "source_rejected" || item.outcome === "stt_empty") >= 0.6) {
    findings.push({
      area: "filtering",
      severity: "warning",
      title: "Most speech is being filtered",
      detail: "Recent turns were too short, filler-only, noise or unfinished, so they were not relayed. Ask speakers to finish full sentences and check mic quality.",
    });
  }
  const blocked = brse.speakers.some((speaker) => speaker.status === "blocked_due_to_overlap");
  if (blocked || share(traces, (item) => item.outcome === "relay_suppressed") >= 0.4 || (brse.queue_depth ?? 0) >= 3) {
    findings.push({
      area: "overlap",
      severity: "warning",
      title: "People are talking over each other",
      detail: `BRSE relays one speaker at a time; others wait or are summarized.${brse.queue_depth ? ` Queue depth: ${brse.queue_depth}.` : ""}`,
    });
  }
  if (traces.some((item) => item.outcome === "output_rejected")) {
    findings.push({ area: "translation", severity: "warning", title: "Some translations were rejected", detail: "The model returned unusable text (meta or narrator style), so it was not published." });
  }
  if (traces.some((item) => item.issue_code === "TTS_NO_AUDIO")) {
    findings.push({ area: "tts", severity: "warning", title: "Relay text arrived without AI voice", detail: "Voice + Text is on but no audio was produced for some relays." });
  }
  if (traces.some((item) => item.issue_code === "RELAY_TOO_LATE" || item.issue_code === "RELAY_SLOW")) {
    findings.push({ area: "delivery", severity: "warning", title: "Relays are late", detail: "Some relays were dropped or delivered after the freshness limit." });
  }

  const delivered = traces.filter((item) => item.outcome === "delivered" || item.outcome === "caption_delivered");
  if (!findings.some((finding) => finding.severity === "error" || finding.severity === "warning")) {
    findings.push(
      delivered.length
        ? { area: "healthy", severity: "ok", title: "Relay is working", detail: `${delivered.length} of the last ${traces.length} utterances were delivered.` }
        : { area: "no_activity", severity: "info", title: "Nothing delivered recently", detail: "Recent speech did not need translation or was filtered." },
    );
  }
  return findings;
}
