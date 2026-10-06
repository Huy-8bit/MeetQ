// Package room reimplements the non-AI room domain of the Python gateway
// (BE/server/service/gateway): create/join/leave, passwords, lock, roles and
// moderation, screen-share state, and the room-level AI relay *state* (the Python
// interpreter does the AI work when it sees the state change on Redis).
package room

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"meetq/backend-go/internal/httpx"
	"meetq/backend-go/internal/platform"
)

var (
	ErrTokenExpired      = errors.New("token expired")
	ErrTokenInvalid      = errors.New("invalid token")
	ErrTokenRoomMismatch = errors.New("token room mismatch")
)

// Claims are the room-token claims (server/service/gateway/auth.py, python-jose HS256).
type Claims map[string]any

func (c Claims) String(key string) string {
	s, _ := c[key].(string)
	return s
}

func (c Claims) ParticipantID() string { return c.String("participant_id") }
func (c Claims) SessionID() string     { return c.String("session_id") }

// IssueRoomToken mirrors issue_room_token.
func IssueRoomToken(roomID, participantID, sessionID, displayName, language, secret string, ttl time.Duration) (string, error) {
	now := platform.NowUTC()
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"room_id":        roomID,
		"participant_id": participantID,
		"session_id":     sessionID,
		"display_name":   displayName,
		"language":       language,
		"exp":            now.Add(ttl).Unix(),
		"iat":            now.Unix(),
	})
	return token.SignedString([]byte(secret))
}

// VerifyRoomToken mirrors verify_room_token.
func VerifyRoomToken(token, secret, expectedRoomID string) (Claims, error) {
	claims := jwt.MapClaims{}
	_, err := jwt.NewParser(jwt.WithValidMethods([]string{"HS256"})).ParseWithClaims(token, claims, func(*jwt.Token) (any, error) {
		return []byte(secret), nil
	})
	if err != nil {
		if errors.Is(err, jwt.ErrTokenExpired) {
			return nil, ErrTokenExpired
		}
		return nil, ErrTokenInvalid
	}
	if expectedRoomID != "" {
		if roomID, _ := claims["room_id"].(string); roomID != expectedRoomID {
			return nil, ErrTokenRoomMismatch
		}
	}
	return Claims(claims), nil
}

// bearer mirrors fastapi.security.HTTPBearer (scheme/credential split on the first space).
func bearer(r *http.Request) (string, bool) {
	authorization := r.Header.Get("Authorization")
	if authorization == "" {
		return "", false
	}
	scheme, credentials, _ := strings.Cut(authorization, " ")
	if scheme == "" || credentials == "" || strings.ToLower(scheme) != "bearer" {
		return "", false
	}
	return credentials, true
}

// RequireToken mirrors verify_token_dependency (FastAPI {"detail": ...} errors).
func RequireToken(r *http.Request, secret, roomID string) (Claims, error) {
	token, ok := bearer(r)
	if !ok {
		return nil, httpx.ErrNotAuthenticated
	}
	claims, err := VerifyRoomToken(token, secret, roomID)
	switch {
	case errors.Is(err, ErrTokenExpired):
		return nil, &httpx.DetailError{Status: 401, Detail: httpx.Envelope("invalid_token", "token expired", nil)}
	case errors.Is(err, ErrTokenInvalid):
		return nil, &httpx.DetailError{Status: 401, Detail: httpx.Envelope("invalid_token", "invalid token", nil)}
	case errors.Is(err, ErrTokenRoomMismatch):
		return nil, &httpx.DetailError{Status: 403, Detail: httpx.Envelope("token_room_mismatch", "room mismatch", nil)}
	}
	return claims, err
}

// OptionalToken mirrors optional_token_dependency: any problem means "no token".
func OptionalToken(r *http.Request, secret, roomID string) Claims {
	token, ok := bearer(r)
	if !ok {
		return nil
	}
	claims, err := VerifyRoomToken(token, secret, roomID)
	if err != nil {
		return nil
	}
	return claims
}
