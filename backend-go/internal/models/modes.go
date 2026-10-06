// Package models mirrors the Python gateway's pydantic models and meeting-mode
// rules (BE/server/models.py, BE/server/meeting_modes.py). The JSON written to
// Redis must stay readable by the Python interpreter (AI) and gateway.
package models

import "strings"

const (
	MeetingModeDirectTranslation = "direct_translation"
	MeetingModeBrseRelay         = "brse_relay"
	MeetingModeBrseSilentSummary = "brse_silent_summary"

	BrseModeRelay         = "relay"
	BrseModeSilentSummary = "silent_summary"
	DefaultBrseMode       = BrseModeRelay

	BrseOutputVoiceText     = "voice_text"
	BrseOutputTextOnly      = "text_only"
	DefaultBrseOutputMode   = BrseOutputVoiceText
	DowngradeMultiLanguage  = "multi_language_text_only"
	SuppressedOneLanguage   = "one_language_no_cross_language_voice_relay"
	SuppressedTextOnly      = "brse_text_only_output_mode"
	SuppressedSilentSummary = "brse_silent_summary_mode"

	RouteSingleLanguage = "single_language_source_capture"
	RouteTwoLanguage    = "two_language_relay"
	RouteMultiLanguage  = "multi_language_text_caption"

	InterpreterModePerListener     = "per_listener"
	InterpreterModeBrseParticipant = "brse_participant"

	KindHuman       = "human"
	KindVirtualBrse = "virtual_brse"

	BrseParticipantID          = "brse_ai"
	BrseParticipantDisplayName = "BRSE AI"
	BrseLiveKitIdentityPrefix  = "interp::brse_ai"

	DefaultBrseEnabled = true
)

// SupportedLanguages is PLATFORM_SUPPORTED_LANGS (order matters for responses).
var SupportedLanguages = []string{"vi", "en", "ja", "zh", "ko", "fr", "es"}

// DefaultRoomLanguages is DEFAULT_ROOM_MEETING_LANGUAGES.
var DefaultRoomLanguages = []string{"vi", "ja"}

func IsSupportedLanguage(code string) bool {
	for _, l := range SupportedLanguages {
		if l == code {
			return true
		}
	}
	return false
}

func BrseLiveKitIdentity(roomID string) string { return BrseLiveKitIdentityPrefix + "::" + roomID }

func NormalizeBrseMode(value string) string {
	if value == BrseModeSilentSummary {
		return BrseModeSilentSummary
	}
	return BrseModeRelay
}

func NormalizeBrseOutputMode(value string) string {
	if value == BrseOutputTextOnly {
		return BrseOutputTextOnly
	}
	return BrseOutputVoiceText
}

// NormalizeRoomLanguagesForRuntime filters to supported languages, de-duplicates, and
// falls back to the default pair.
func NormalizeRoomLanguagesForRuntime(langs []string) []string {
	out := []string{}
	for _, raw := range langs {
		lang := strings.ToLower(strings.TrimSpace(raw))
		if !IsSupportedLanguage(lang) || contains(out, lang) {
			continue
		}
		out = append(out, lang)
	}
	if len(out) == 0 {
		return append([]string{}, DefaultRoomLanguages...)
	}
	return out
}

func RouteStrategy(langs []string) string {
	room := NormalizeRoomLanguagesForRuntime(langs)
	switch len(room) {
	case 1:
		return RouteSingleLanguage
	case 2:
		return RouteTwoLanguage
	}
	return RouteMultiLanguage
}

// ResolveEffectiveOutputMode downgrades voice to text for rooms with 3+ languages.
func ResolveEffectiveOutputMode(langs []string, requested string) (string, *string) {
	mode := NormalizeBrseOutputMode(requested)
	room := NormalizeRoomLanguagesForRuntime(langs)
	if len(room) > 2 && mode == BrseOutputVoiceText {
		reason := DowngradeMultiLanguage
		return BrseOutputTextOnly, &reason
	}
	return mode, nil
}

func SelectableOutputModes(langs []string) []string {
	if VoiceRelayAllowed(langs) {
		return []string{BrseOutputVoiceText, BrseOutputTextOnly}
	}
	return []string{BrseOutputTextOnly}
}

func VoiceRelayAllowed(langs []string) bool {
	return len(NormalizeRoomLanguagesForRuntime(langs)) == 2
}

func MeetingModeForBrseMode(mode string) string {
	if NormalizeBrseMode(mode) == BrseModeSilentSummary {
		return MeetingModeBrseSilentSummary
	}
	return MeetingModeBrseRelay
}

func relayTextEnabled(enabled bool, mode string) bool {
	return enabled && NormalizeBrseMode(mode) == BrseModeRelay
}

func audioOutputEnabled(enabled bool, mode, outputMode string, langs []string) bool {
	if langs != nil && !VoiceRelayAllowed(langs) {
		return false
	}
	return relayTextEnabled(enabled, mode) && NormalizeBrseOutputMode(outputMode) == BrseOutputVoiceText
}

// BuildBrseVirtualParticipant mirrors build_brse_virtual_participant.
func BuildBrseVirtualParticipant(roomID string, joinedAt *string, langs []string, brseMode, outputMode string) ParticipantSnapshot {
	room := NormalizeRoomLanguagesForRuntime(langs)
	mode := NormalizeBrseMode(brseMode)
	requested := NormalizeBrseOutputMode(outputMode)
	effective, downgrade := ResolveEffectiveOutputMode(room, requested)
	textEnabled := relayTextEnabled(true, mode)
	audio := audioOutputEnabled(true, mode, effective, room)
	policy := "source_only_internal"
	if textEnabled {
		policy = "publish_realtime"
	}
	identity := BrseLiveKitIdentity(roomID)
	var reason any
	if downgrade != nil {
		reason = *downgrade
	}
	return ParticipantSnapshot{
		ParticipantID:   BrseParticipantID,
		DisplayName:     BrseParticipantDisplayName,
		Language:        "auto",
		Status:          "connected",
		JoinedAt:        joinedAt,
		Kind:            KindVirtualBrse,
		IsVirtual:       true,
		LiveKitIdentity: &identity,
		Metadata: map[string]any{
			"meeting_mode":                 MeetingModeForBrseMode(mode),
			"brse_mode":                    mode,
			"brse_output_mode":             effective,
			"requested_brse_output_mode":   requested,
			"output_mode_downgrade_reason": reason,
			"interpreter_mode":             InterpreterModeBrseParticipant,
			"room_languages":               room,
			"meeting_languages":            room,
			"route_strategy":               RouteStrategy(room),
			"publishes_audio":              audio,
			"publishes_text":               textEnabled,
			"publishes_video":              false,
			"subscribes_human_audio":       true,
			"summary_ready":                mode == BrseModeSilentSummary,
			"relay_transcript_policy":      policy,
		},
		Role: RoleParticipant,
	}
}

func buildRelayLanguageTargets(langs []string) map[string][]string {
	room := NormalizeRoomLanguagesForRuntime(langs)
	out := map[string][]string{}
	for _, src := range room {
		targets := []string{}
		for _, tgt := range room {
			if tgt != src {
				targets = append(targets, tgt)
			}
		}
		out[src] = targets
	}
	return out
}

func buildRelayLanguageMap(langs []string) map[string]string {
	pair := NormalizeRoomLanguagesForRuntime(langs)
	if len(pair) != 2 || pair[0] == pair[1] {
		return map[string]string{}
	}
	return map[string]string{pair[0]: pair[1], pair[1]: pair[0]}
}

// BuildAudioRouting mirrors build_brse_audio_routing.
func BuildAudioRouting(langs []string, brseMode, outputMode string) AudioRouting {
	room := NormalizeRoomLanguagesForRuntime(langs)
	mode := NormalizeBrseMode(brseMode)
	requested := NormalizeBrseOutputMode(outputMode)
	effective, downgrade := ResolveEffectiveOutputMode(room, requested)
	textEnabled := relayTextEnabled(true, mode)
	audio := audioOutputEnabled(true, mode, effective, room)
	model := "brse_text_only_relay"
	if mode == BrseModeSilentSummary {
		model = "brse_silent_listener"
	} else if audio {
		model = "brse_participant_audio"
	}
	var suppressed *string
	switch {
	case mode == BrseModeSilentSummary:
		suppressed = strPtr(SuppressedSilentSummary)
	case downgrade != nil:
		suppressed = strPtr(*downgrade)
	case textEnabled && len(room) == 1 && !audio:
		suppressed = strPtr(SuppressedOneLanguage)
	case textEnabled && !audio:
		suppressed = strPtr(SuppressedTextOnly)
	}
	cross := "human_original_only"
	aiAudio := "disabled"
	if audio {
		cross = "human_original_plus_brse"
		aiAudio = "virtual_participant_track"
	}
	policy := "source_only_internal"
	if textEnabled {
		policy = "publish_realtime"
	}
	return AudioRouting{
		Model:                     model,
		CrossLanguageRemoteAudio:  cross,
		CanonicalRemoteAudio:      "human_original_track",
		SameLanguagePolicy:        "human_passthrough",
		AIRelayAudio:              aiAudio,
		InterpreterMode:           InterpreterModeBrseParticipant,
		BridgeStrategy:            "participant_language_preference",
		RelayLanguageMap:          buildRelayLanguageMap(room),
		RelayLanguageTargets:      buildRelayLanguageTargets(room),
		VirtualParticipantID:      BrseParticipantID,
		BrseMode:                  mode,
		BrseOutputMode:            effective,
		RequestedBrseOutputMode:   requested,
		OutputModeDowngradeReason: downgrade,
		AIAudioOutputEnabled:      audio,
		RelayTextOutputEnabled:    textEnabled,
		AIAudioSuppressedReason:   suppressed,
		SourceTranscriptCapture:   true,
		RelayTranscriptPolicy:     policy,
		RouteStrategy:             RouteStrategy(room),
		RoomLanguageCount:         len(room),
	}
}

// IsActiveHuman mirrors is_active_human_participant.
func IsActiveHuman(p ParticipantSnapshot) bool {
	return !p.IsVirtual && p.Kind != KindVirtualBrse && p.Status != "disconnected"
}

func ActiveHumanCount(ps []ParticipantSnapshot) int {
	n := 0
	for _, p := range ps {
		if IsActiveHuman(p) {
			n++
		}
	}
	return n
}

func contains(list []string, v string) bool {
	for _, item := range list {
		if item == v {
			return true
		}
	}
	return false
}

func strPtr(s string) *string { return &s }
