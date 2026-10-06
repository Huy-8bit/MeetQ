// Package ai is the only way the Go backend reaches the Python AI service.
//
// Two channels exist, both owned by Python on the AI side:
//
//  1. Relay control (start/stop BRSE AI, Voice+Text <-> Text Only) is the existing
//     Redis contract: Go updates room state in Redis and publishes room.* /
//     participant.* events on the gateway control channel; the Python interpreter
//     reacts (see room.Service.publish). Nothing AI-related runs in Go.
//  2. Request/response AI work (summaries, chat translation) goes through the
//     internal HTTP API below (BE/server/service/ai_internal/api.py), authenticated
//     with a service token and never exposed publicly.
package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"

	"meetq/backend-go/internal/httpx"
)

const TokenHeader = "X-Internal-Service-Token"

var (
	requestDuration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "python_ai_request_duration_seconds",
		Help:    "Latency of Go -> Python AI internal API calls.",
		Buckets: []float64{0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120},
	}, []string{"operation"})
	requestErrors = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "python_ai_request_errors_total",
		Help: "Failed Go -> Python AI internal API calls (transport errors and 5xx).",
	}, []string{"operation"})
)

func init() {
	prometheus.MustRegister(requestDuration, requestErrors)
}

// Error is a failure reported by (or reaching) the AI service.
type Error struct {
	Status  int
	Code    string
	Message string
	Details map[string]any
}

func (e *Error) Error() string { return fmt.Sprintf("python ai %d %s", e.Status, e.Code) }

// ErrUnavailable means the AI service could not be reached in time.
var ErrUnavailable = errors.New("python ai service unavailable")

type Client struct {
	BaseURL        string
	Token          string
	Timeout        time.Duration
	SummaryTimeout time.Duration
	HTTP           *http.Client
}

func New(baseURL, token string, timeout, summaryTimeout time.Duration) *Client {
	return &Client{
		BaseURL:        strings.TrimRight(baseURL, "/"),
		Token:          token,
		Timeout:        timeout,
		SummaryTimeout: summaryTimeout,
		// Per-call deadlines come from the context; this is a hard upper bound.
		HTTP: &http.Client{Timeout: summaryTimeout + 5*time.Second},
	}
}

func (c *Client) Configured() bool { return c != nil && c.BaseURL != "" && c.Token != "" }

func (c *Client) call(ctx context.Context, operation, method, path string, timeout time.Duration, body any, out any) error {
	if !c.Configured() {
		return ErrUnavailable
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set(TokenHeader, c.Token)
	if id := httpx.RequestIDFrom(ctx); id != "" {
		req.Header.Set("X-Request-ID", id)
	}
	started := time.Now()
	resp, err := c.HTTP.Do(req)
	requestDuration.WithLabelValues(operation).Observe(time.Since(started).Seconds())
	if err != nil {
		requestErrors.WithLabelValues(operation).Inc()
		return errors.Join(ErrUnavailable, err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		requestErrors.WithLabelValues(operation).Inc()
		return errors.Join(ErrUnavailable, err)
	}
	if resp.StatusCode >= 300 {
		if resp.StatusCode >= 500 {
			requestErrors.WithLabelValues(operation).Inc()
		}
		var envelope struct {
			Error struct {
				Code    string         `json:"code"`
				Message string         `json:"message"`
				Details map[string]any `json:"details"`
			} `json:"error"`
		}
		_ = json.Unmarshal(raw, &envelope)
		code := envelope.Error.Code
		if code == "" {
			code = "ai_service_error"
		}
		return &Error{Status: resp.StatusCode, Code: code, Message: envelope.Error.Message, Details: envelope.Error.Details}
	}
	if out != nil && len(raw) > 0 {
		return json.Unmarshal(raw, out)
	}
	return nil
}

// SummaryRequest asks Python to generate (or reuse) a meeting summary.
type SummaryRequest struct {
	Type                   *string `json:"type"`
	Language               *string `json:"language"`
	RequesterParticipantID *string `json:"requester_participant_id"`
	RequesterLanguage      *string `json:"requester_language"`
}

// GenerateSummary is not idempotent (LLM call): never retried.
func (c *Client) GenerateSummary(ctx context.Context, roomID string, req SummaryRequest) (json.RawMessage, error) {
	var out json.RawMessage
	err := c.call(ctx, "generate_summary", http.MethodPost, "/internal/ai/rooms/"+roomID+"/summary", c.SummaryTimeout, req, &out)
	return out, err
}

// FinalSummaryRequest triggers the end-of-meeting summary; Python accepts and runs it in the background.
type FinalSummaryRequest struct {
	TriggerReason     string  `json:"trigger_reason"`
	EndedAt           *string `json:"ended_at"`
	RequesterLanguage *string `json:"requester_language"`
}

func (c *Client) RequestFinalSummary(ctx context.Context, roomID string, req FinalSummaryRequest) error {
	return c.call(ctx, "final_summary", http.MethodPost, "/internal/ai/rooms/"+roomID+"/final-summary", c.Timeout, req, nil)
}

type Translation struct {
	Language string `json:"language"`
	Text     string `json:"text"`
}

// TranslateChat returns the translations Python produced; failed targets are simply missing.
func (c *Client) TranslateChat(ctx context.Context, roomID, text, srcLang string, roomLanguages []string) ([]Translation, error) {
	var out struct {
		Translations []Translation `json:"translations"`
	}
	err := c.call(ctx, "translate_chat", http.MethodPost, "/internal/ai/chat/translate", c.Timeout, map[string]any{
		"room_id": roomID, "text": text, "src_lang": srcLang, "room_languages": roomLanguages,
	}, &out)
	return out.Translations, err
}

// Health checks the internal API (diagnostics only; /readiness never calls it).
func (c *Client) Health(ctx context.Context) error {
	return c.call(ctx, "health", http.MethodGet, "/internal/ai/health", 3*time.Second, nil, nil)
}
