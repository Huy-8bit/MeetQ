package models

import (
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"meetq/backend-go/internal/platform"
)

type ActionItem struct {
	Text  string  `json:"text"`
	Owner *string `json:"owner"`
	Due   *string `json:"due"`
}

type ParticipantItem struct {
	ParticipantID *string `json:"participant_id"`
	DisplayName   *string `json:"display_name"`
	Summary       string  `json:"summary"`
}

// MeetingSummary is MeetingSummaryResponse (BE/server/models.py), built from the stored
// document with the same normalization as room_history + the pydantic validator.
type MeetingSummary struct {
	RoomID                string            `json:"room_id"`
	SummaryID             *string           `json:"summary_id"`
	SummaryType           string            `json:"summary_type"`
	Status                string            `json:"status"`
	CreatedAt             string            `json:"created_at"`
	GeneratedAt           *string           `json:"generated_at"`
	SummaryLanguage       string            `json:"summary_language"`
	SummaryText           *string           `json:"summary_text"`
	KeyPoints             []string          `json:"key_points"`
	Highlights            []string          `json:"highlights"`
	Decisions             []string          `json:"decisions"`
	ActionItems           []string          `json:"action_items"`
	ActionItemDetails     []ActionItem      `json:"action_item_details"`
	RisksBlockers         []string          `json:"risks_blockers"`
	OpenQuestions         []string          `json:"open_questions"`
	NextSteps             []string          `json:"next_steps"`
	ParticipantHighlights []ParticipantItem `json:"participant_highlights"`
	ParticipantSummary    []ParticipantItem `json:"participant_summary"`
	DurationSeconds       *int64            `json:"duration_seconds"`
	SourceWindow          map[string]any    `json:"source_window"`
	SourceStats           map[string]any    `json:"source_stats"`
	Error                 *string           `json:"error"`
}

// summaryStringList is room_history._text_list (strings or {"text": ...} items).
func summaryStringList(v any) []string {
	out := []string{}
	items, ok := asList(v)
	if !ok {
		return out
	}
	for _, item := range items {
		var text string
		switch t := item.(type) {
		case string:
			text = strings.TrimSpace(t)
		case map[string]any:
			text = strings.TrimSpace(stringOf(t["text"]))
		case bson.M:
			text = strings.TrimSpace(stringOf(t["text"]))
		case bson.D:
			text = strings.TrimSpace(stringOf(DocToMap(t)["text"]))
		}
		if text != "" {
			out = append(out, text)
		}
	}
	return out
}

// strictStringList is room_history._string_list (strings only, no dicts).
func strictStringList(v any) []string {
	out := []string{}
	items, ok := asList(v)
	if !ok {
		return out
	}
	for _, item := range items {
		if s, ok := item.(string); ok && strings.TrimSpace(s) != "" {
			out = append(out, strings.TrimSpace(s))
		}
	}
	return out
}

func asList(v any) ([]any, bool) {
	switch t := v.(type) {
	case []any:
		return t, true
	case bson.A:
		return []any(t), true
	case []string:
		out := make([]any, len(t))
		for i, s := range t {
			out[i] = s
		}
		return out, true
	}
	return nil, false
}

func asMap(v any) (map[string]any, bool) {
	switch t := v.(type) {
	case map[string]any:
		return t, true
	case bson.M:
		return map[string]any(t), true
	case bson.D:
		return DocToMap(t), true
	}
	return nil, false
}

// DocToMap converts an ordered BSON document to a map (bson.D.Map was removed in driver v2).
func DocToMap(d bson.D) map[string]any {
	out := make(map[string]any, len(d))
	for _, e := range d {
		out[e.Key] = e.Value
	}
	return out
}

func stringOf(v any) string {
	s, _ := v.(string)
	return s
}

func optionalString(v any) *string {
	s, ok := v.(string)
	if !ok {
		return nil
	}
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	return &s
}

func actionDetails(v any) []ActionItem {
	out := []ActionItem{}
	items, ok := asList(v)
	if !ok {
		return out
	}
	for _, item := range items {
		if s, ok := item.(string); ok {
			if s = strings.TrimSpace(s); s != "" {
				out = append(out, ActionItem{Text: s})
			}
			continue
		}
		if m, ok := asMap(item); ok {
			text := strings.TrimSpace(stringOf(m["text"]))
			if text != "" {
				out = append(out, ActionItem{Text: text, Owner: optionalString(m["owner"]), Due: optionalString(m["due"])})
			}
		}
	}
	return out
}

func participantItems(v any) []ParticipantItem {
	out := []ParticipantItem{}
	items, ok := asList(v)
	if !ok {
		return out
	}
	for _, item := range items {
		m, ok := asMap(item)
		if !ok {
			continue
		}
		summary := optionalString(m["summary"])
		if summary == nil {
			continue
		}
		out = append(out, ParticipantItem{ParticipantID: optionalString(m["participant_id"]), DisplayName: optionalString(m["display_name"]), Summary: *summary})
	}
	return out
}

func firstStringList(doc map[string]any, keys ...string) []string {
	for _, key := range keys {
		if list := strictStringList(doc[key]); len(list) > 0 {
			return list
		}
	}
	return []string{}
}

// SummaryFromDoc applies room_history._normalize_meeting_recap_doc and the
// MeetingSummaryResponse validator to a stored meeting_summaries document.
func SummaryFromDoc(doc map[string]any) MeetingSummary {
	keyPoints := strictStringList(doc["key_points"])
	if len(keyPoints) == 0 {
		keyPoints = strictStringList(doc["highlights"])
	}
	actionItems := summaryStringList(doc["action_items"])
	detailSource := doc["action_item_details"]
	if l, ok := asList(detailSource); !ok || len(l) == 0 {
		detailSource = doc["action_items"]
	}
	details := actionDetails(detailSource)
	if len(actionItems) == 0 {
		for _, d := range details {
			actionItems = append(actionItems, d.Text)
		}
	}
	highlights := participantItems(doc["participant_highlights"])
	if len(highlights) == 0 {
		highlights = participantItems(doc["participant_summary"])
	}
	summary := MeetingSummary{
		RoomID:                stringOf(doc["room_id"]),
		SummaryID:             optionalRaw(doc["summary_id"]),
		SummaryType:           nonEmptyStr(stringOf(doc["summary_type"]), "final"),
		Status:                stringOf(doc["status"]),
		CreatedAt:             timeString(doc["created_at"]),
		GeneratedAt:           optionalTime(doc["generated_at"]),
		SummaryLanguage:       nonEmptyStr(stringOf(doc["summary_language"]), "en"),
		SummaryText:           optionalRaw(doc["summary_text"]),
		KeyPoints:             keyPoints,
		Highlights:            append([]string{}, keyPoints...),
		Decisions:             strictStringList(doc["decisions"]),
		ActionItems:           actionItems,
		ActionItemDetails:     details,
		RisksBlockers:         firstStringList(doc, "risks_blockers", "blockers", "risks", "issues"),
		OpenQuestions:         firstStringList(doc, "open_questions", "unanswered_questions", "questions"),
		NextSteps:             firstStringList(doc, "next_steps", "follow_ups", "follow_up"),
		ParticipantHighlights: highlights,
		ParticipantSummary:    append([]ParticipantItem{}, highlights...),
		SourceWindow:          JSONMap(doc["source_window"]),
		SourceStats:           JSONMap(doc["source_stats"]),
		Error:                 optionalRaw(doc["error"]),
	}
	switch d := doc["duration_seconds"].(type) {
	case int32:
		v := int64(d)
		summary.DurationSeconds = &v
	case int64:
		summary.DurationSeconds = &d
	case float64:
		v := int64(d)
		summary.DurationSeconds = &v
	}
	return summary
}

func optionalRaw(v any) *string {
	if s, ok := v.(string); ok {
		return &s
	}
	return nil
}

func nonEmptyStr(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

func timeString(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case bson.DateTime:
		return platform.ISO(t.Time())
	case time.Time:
		return platform.ISO(t)
	}
	return ""
}

func optionalTime(v any) *string {
	if v == nil {
		return nil
	}
	s := timeString(v)
	if s == "" {
		return nil
	}
	return &s
}

// JSONMap converts BSON values into JSON-friendly ones (dates as ISO strings).
func JSONMap(v any) map[string]any {
	m, ok := asMap(v)
	if !ok {
		return map[string]any{}
	}
	out := map[string]any{}
	for k, item := range m {
		out[k] = JSONValue(item)
	}
	return out
}

func JSONValue(v any) any {
	switch t := v.(type) {
	case bson.M, bson.D, map[string]any:
		return JSONMap(t)
	case bson.A:
		out := make([]any, len(t))
		for i, item := range t {
			out[i] = JSONValue(item)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, item := range t {
			out[i] = JSONValue(item)
		}
		return out
	case bson.DateTime:
		return platform.ISO(t.Time())
	case time.Time:
		return platform.ISO(t)
	case bson.ObjectID:
		return t.Hex()
	}
	return v
}
