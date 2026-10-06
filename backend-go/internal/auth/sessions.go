// Package auth reimplements BE/server/service/auth: opaque Redis sessions behind
// HttpOnly cookies, Google ID-token sign-in and username/password admin sign-in.
//
// Sessions are byte-compatible with the Python gateway: the browser holds a random
// token, Redis stores JSON under brseai:v1:auth:{realm}:session:{sha256(token)}.
// A user signed in through Python is signed in on Go (and the other way round).
package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"

	"meetq/backend-go/internal/platform"
)

const (
	UserRealm  = "user"
	AdminRealm = "admin"
	keyPrefix  = "brseai:v1:auth"

	UserCookie      = "meetq_session"
	AdminCookie     = "meetq_admin_session"
	AdminCookiePath = "/api/admin"
)

func sessionKey(realm, token string) string {
	sum := sha256.Sum256([]byte(token))
	return keyPrefix + ":" + realm + ":session:" + hex.EncodeToString(sum[:])
}

type SessionStore struct{ R *redis.Client }

// newToken matches secrets.token_urlsafe(32).
func newToken() string {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(buf)
}

// Create stores {...data, realm, created_at, expires_at} for ttl.
func (s *SessionStore) Create(ctx context.Context, realm string, data map[string]any, ttl time.Duration) (string, map[string]any, error) {
	token := newToken()
	now := platform.NowUTC()
	session := map[string]any{}
	for k, v := range data {
		session[k] = v
	}
	session["realm"] = realm
	session["created_at"] = platform.ISO(now)
	session["expires_at"] = platform.ISO(now.Add(ttl))
	raw, err := json.Marshal(session)
	if err != nil {
		return "", nil, err
	}
	if err := s.R.Set(ctx, sessionKey(realm, token), raw, ttl).Err(); err != nil {
		return "", nil, err
	}
	return token, session, nil
}

func (s *SessionStore) Get(ctx context.Context, realm, token string) (map[string]any, error) {
	if token == "" {
		return nil, nil
	}
	raw, err := s.R.Get(ctx, sessionKey(realm, token)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var session map[string]any
	if err := json.Unmarshal(raw, &session); err != nil {
		return nil, nil
	}
	if session["realm"] != realm {
		return nil, nil
	}
	return session, nil
}

func (s *SessionStore) Delete(ctx context.Context, realm, token string) error {
	if token == "" {
		return nil
	}
	return s.R.Del(ctx, sessionKey(realm, token)).Err()
}

// ── Cookies (Starlette set_cookie / delete_cookie attributes) ──────────────

func setCookie(w http.ResponseWriter, name, value, path string, maxAge int, secure bool, sameSite string) {
	cookie := name + "=" + value + "; HttpOnly; Max-Age=" + strconv.Itoa(maxAge) + "; Path=" + path + "; SameSite=" + sameSite
	if secure {
		cookie += "; Secure"
	}
	w.Header().Add("Set-Cookie", cookie)
}

func deleteCookie(w http.ResponseWriter, name, path string, secure bool, sameSite string) {
	expires := platform.NowUTC().Format("Mon, 02 Jan 2006 15:04:05 GMT")
	cookie := name + `=""; expires=` + expires + "; HttpOnly; Max-Age=0; Path=" + path + "; SameSite=" + sameSite
	if secure {
		cookie += "; Secure"
	}
	w.Header().Add("Set-Cookie", cookie)
}

func SetUserCookie(w http.ResponseWriter, token string, ttlSeconds int, secure bool) {
	setCookie(w, UserCookie, token, "/", ttlSeconds, secure, "lax")
}

func ClearUserCookie(w http.ResponseWriter, secure bool) {
	deleteCookie(w, UserCookie, "/", secure, "lax")
}

func SetAdminCookie(w http.ResponseWriter, token string, ttlSeconds int, secure bool) {
	setCookie(w, AdminCookie, token, AdminCookiePath, ttlSeconds, secure, "strict")
}

func ClearAdminCookie(w http.ResponseWriter, secure bool) {
	deleteCookie(w, AdminCookie, AdminCookiePath, secure, "strict")
}

func CookieValue(r *http.Request, name string) string {
	c, err := r.Cookie(name)
	if err != nil {
		return ""
	}
	return c.Value
}
