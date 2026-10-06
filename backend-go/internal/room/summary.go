package room

import (
	"context"
	"encoding/json"
	"errors"

	"meetq/backend-go/internal/ai"
	"meetq/backend-go/internal/models"
)

var (
	ErrSummaryNotFound    = errors.New("meeting summary not found")
	ErrInvalidSummaryType = errors.New("invalid summary type")
)

// GetMeetingSummary reads a stored summary (non-AI): RoomService.get_meeting_summary.
func (s *Service) GetMeetingSummary(ctx context.Context, roomID, summaryType string) (*models.MeetingSummary, error) {
	if !s.History.Enabled() {
		return nil, ErrSummaryNotFound
	}
	switch summaryType {
	case "", "final":
		summaryType = "final"
	case "interim":
	default:
		return nil, ErrInvalidSummaryType
	}
	doc, err := s.History.GetMeetingSummary(ctx, roomID, summaryType)
	if err != nil {
		return nil, err
	}
	if doc == nil {
		return nil, ErrSummaryNotFound
	}
	summary := models.SummaryFromDoc(doc)
	return &summary, nil
}

// GenerateMeetingSummary delegates generation to the Python AI service. Go has already
// authenticated and authorized the caller; Python reads the same Redis/Mongo state.
func (s *Service) GenerateMeetingSummary(ctx context.Context, roomID string, summaryType, language *string, claims Claims) (json.RawMessage, error) {
	if s.AI == nil || !s.AI.Configured() {
		return nil, &ai.Error{Status: 503, Code: "meeting_summary_unavailable", Message: "Meeting summary persistence is unavailable"}
	}
	req := ai.SummaryRequest{Type: summaryType, Language: language}
	if claims != nil {
		if pid := claims.ParticipantID(); pid != "" {
			req.RequesterParticipantID = &pid
		}
		if lang := claims.String("language"); lang != "" {
			req.RequesterLanguage = &lang
		}
	}
	return s.AI.GenerateSummary(ctx, roomID, req)
}
