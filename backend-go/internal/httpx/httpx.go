// Package httpx contains the HTTP conventions shared by every handler: JSON
// rendering, the Python-compatible error envelopes and request decoding.
package httpx

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
)

// Error is the standard API error, rendered as {"error": {"code", "message", "details"?}}
// (Python: AdminApiError / _error_response).
type Error struct {
	Status  int
	Code    string
	Message string
	Details map[string]any
	// Headers added to the response (e.g. Retry-After).
	Headers map[string]string
}

func (e *Error) Error() string { return e.Code + ": " + e.Message }

func NewError(status int, code, message string) *Error {
	return &Error{Status: status, Code: code, Message: message}
}

func (e *Error) WithDetails(details map[string]any) *Error {
	e.Details = details
	return e
}

// DetailError renders FastAPI's HTTPException shape {"detail": <value>}; used where the
// Python gateway raises HTTPException (room token checks, device-test errors).
type DetailError struct {
	Status  int
	Detail  any
	Headers map[string]string
}

func (e *DetailError) Error() string { return "detail error " + strconv.Itoa(e.Status) }

// Common FastAPI responses.
var (
	ErrNotAuthenticated = &DetailError{Status: http.StatusUnauthorized, Detail: "Not authenticated", Headers: map[string]string{"WWW-Authenticate": "Bearer"}}
)

func Envelope(code, message string, details map[string]any) map[string]any {
	inner := map[string]any{"code": code, "message": message}
	if len(details) > 0 {
		inner["details"] = details
	}
	return map[string]any{"error": inner}
}

// JSON writes v compactly without HTML escaping (like Starlette's JSONResponse).
func JSON(w http.ResponseWriter, status int, v any) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		http.Error(w, `{"detail":"Internal Server Error"}`, http.StatusInternalServerError)
		return
	}
	body := bytes.TrimRight(buf.Bytes(), "\n")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

func NoContent(w http.ResponseWriter) {
	w.WriteHeader(http.StatusNoContent)
}

// WriteError renders any error with the matching envelope; unknown errors are 500
// with FastAPI's body and are never echoed to the client.
func WriteError(w http.ResponseWriter, err error) {
	var validation *ValidationError
	if errors.As(err, &validation) {
		validation.Render(w)
		return
	}
	var apiErr *Error
	if errors.As(err, &apiErr) {
		for k, v := range apiErr.Headers {
			w.Header().Set(k, v)
		}
		JSON(w, apiErr.Status, Envelope(apiErr.Code, apiErr.Message, apiErr.Details))
		return
	}
	var detail *DetailError
	if errors.As(err, &detail) {
		for k, v := range detail.Headers {
			w.Header().Set(k, v)
		}
		JSON(w, detail.Status, map[string]any{"detail": detail.Detail})
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusInternalServerError)
	_, _ = w.Write([]byte("Internal Server Error"))
}

// Handler is an http handler that returns its error instead of writing it.
type Handler func(w http.ResponseWriter, r *http.Request) error

func (h Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if err := h(w, r); err != nil {
		if !isClientError(err) {
			LoggerFrom(r.Context()).Error("request failed", "error", err.Error())
		}
		WriteError(w, err)
	}
}

func isClientError(err error) bool {
	var validation *ValidationError
	if errors.As(err, &validation) {
		return true
	}
	var apiErr *Error
	if errors.As(err, &apiErr) {
		return apiErr.Status < 500
	}
	var detail *DetailError
	return errors.As(err, &detail)
}

// DecodeJSON reads a JSON body into a generic map (validation is done by each
// handler against the Python contract). An empty body yields (nil, nil).
func DecodeJSON(r *http.Request, limit int64) (map[string]any, []byte, error) {
	if limit <= 0 {
		limit = 1 << 20
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, limit))
	if err != nil {
		return nil, nil, err
	}
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 {
		return nil, raw, nil
	}
	var out map[string]any
	dec := json.NewDecoder(bytes.NewReader(trimmed))
	dec.UseNumber()
	if err := dec.Decode(&out); err != nil {
		return nil, raw, err
	}
	return out, raw, nil
}
