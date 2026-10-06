package auth

import (
	"context"
	"errors"
	"net"
	"net/http"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/httpx"
)

type Service struct {
	Cfg            *config.Config
	Sessions       *SessionStore
	Google         *GoogleVerifier
	History        *history.Repository
	GoogleFailures *RateLimiter
	AdminFailures  *RateLimiter
	// FailedLoginDelay slows down admin password guessing (Python: 0.4 s).
	FailedLoginDelay time.Duration
}

func ErrAuthRequired() error { return httpx.NewError(401, "auth_required", "Sign in required.") }
func ErrSessionExpired() error {
	return httpx.NewError(401, "session_expired", "Your session has ended. Sign in again.")
}
func ErrAdminAuthRequired() error {
	return httpx.NewError(401, "admin_auth_required", "Admin sign-in required.")
}
func ErrAdminSessionExpired() error {
	return httpx.NewError(401, "admin_session_expired", "Admin session expired.")
}

// CurrentUser returns the signed-in user session or a 401 (Python: current_user).
func (s *Service) CurrentUser(r *http.Request) (map[string]any, error) {
	token := CookieValue(r, UserCookie)
	if token == "" {
		return nil, ErrAuthRequired()
	}
	session, err := s.Sessions.Get(r.Context(), UserRealm, token)
	if err != nil {
		return nil, err
	}
	if session == nil {
		return nil, ErrSessionExpired()
	}
	return session, nil
}

// RequireUser returns nil (no error) when USER_AUTH_REQUIRED is off (Python: require_user).
func (s *Service) RequireUser(r *http.Request) (map[string]any, error) {
	if !s.Cfg.UserAuthRequired {
		return nil, nil
	}
	return s.CurrentUser(r)
}

// CurrentAdmin mirrors auth.dependencies.current_admin.
func (s *Service) CurrentAdmin(r *http.Request) (map[string]any, error) {
	if !s.Cfg.AdminEnabled() {
		return nil, httpx.NewError(503, "admin_disabled", "Admin portal is disabled. Set ADMIN_USERNAME and ADMIN_PASSWORD_HASH.")
	}
	return s.adminSession(r)
}

// RequireAdmin mirrors admin.dependencies.require_admin (used by every /api/admin route).
func (s *Service) RequireAdmin(r *http.Request) (map[string]any, error) {
	if !s.Cfg.AdminEnabled() {
		return nil, httpx.NewError(503, "admin_disabled", "Admin portal is disabled. Set ADMIN_USERNAME and ADMIN_PASSWORD_HASH to enable it.")
	}
	return s.adminSession(r)
}

func (s *Service) adminSession(r *http.Request) (map[string]any, error) {
	token := CookieValue(r, AdminCookie)
	if token == "" {
		return nil, ErrAdminAuthRequired()
	}
	session, err := s.Sessions.Get(r.Context(), AdminRealm, token)
	if err != nil {
		return nil, err
	}
	if session == nil {
		return nil, ErrAdminSessionExpired()
	}
	return session, nil
}

// UserID extracts session["user"]["id"].
func UserID(session map[string]any) string {
	user, _ := session["user"].(map[string]any)
	id, _ := user["id"].(string)
	return id
}

func AdminName(session map[string]any) string {
	admin, _ := session["admin"].(map[string]any)
	if name, _ := admin["username"].(string); name != "" {
		return name
	}
	return "admin"
}

func ClientKey(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || host == "" {
		return "unknown"
	}
	return host
}

// ── Handlers ────────────────────────────────────────────────────────────

func (s *Service) GoogleSignIn(w http.ResponseWriter, r *http.Request) error {
	// FastAPI resolves the verifier dependency before validating the body.
	if strings.TrimSpace(s.Cfg.GoogleClientID) == "" || s.Google == nil {
		return httpx.NewError(503, "auth_unavailable", "Google sign-in is not configured on this server (GOOGLE_CLIENT_ID).")
	}
	body, _, err := httpx.DecodeJSON(r, 64<<10)
	errs := &httpx.ValidationError{}
	credential := ""
	switch {
	case err != nil:
		typ, msg := httpx.MsgJSONInvalid()
		errs.Add([]any{"body", 0}, typ, msg)
	case body == nil:
		typ, msg := httpx.MsgMissing()
		errs.Add([]any{"body"}, typ, msg)
	default:
		value, present, ok := httpx.BodyString(body, "credential")
		switch {
		case !present:
			typ, msg := httpx.MsgMissing()
			errs.Add([]any{"body", "credential"}, typ, msg)
		case !ok:
			typ, msg := httpx.MsgStringType()
			errs.Add([]any{"body", "credential"}, typ, msg)
		case len([]rune(value)) < 1:
			typ, msg := httpx.MsgTooShort(1)
			errs.Add([]any{"body", "credential"}, typ, msg)
		case len([]rune(value)) > 8192:
			typ, msg := httpx.MsgTooLong(8192)
			errs.Add([]any{"body", "credential"}, typ, msg)
		}
		credential = value
	}
	if !errs.Empty() {
		return errs
	}
	ctx := r.Context()
	client := ClientKey(r)
	if s.GoogleFailures.Blocked(ctx, client) {
		return httpx.NewError(429, "too_many_attempts", "Too many sign-in attempts. Try again later.")
	}
	identity, err := s.Google.Verify(ctx, credential)
	if err != nil {
		var tokenErr *GoogleTokenError
		switch {
		case errors.As(err, &tokenErr):
			s.GoogleFailures.Fail(ctx, client)
			// Never log the credential itself.
			httpx.LoggerFrom(ctx).Warn("google sign-in rejected", "client", client, "reason", tokenErr.Reason)
			return httpx.NewError(401, "invalid_google_credential", "Google sign-in could not be verified.")
		case errors.Is(err, ErrAccountNotAllowed):
			return httpx.NewError(403, "account_not_allowed", "This Google account isn't allowed to use MeetQ.")
		default:
			httpx.LoggerFrom(ctx).Error("google sign-in verification failed", "client", client, "error", err.Error())
			return httpx.NewError(503, "auth_unavailable", "Google sign-in is temporarily unavailable.")
		}
	}
	user := map[string]any{
		"id":         GoogleUserID(identity.Subject),
		"email":      identity.Email,
		"name":       ptrOrNil(identity.Name),
		"avatar_url": ptrOrNil(identity.Picture),
	}
	// A fresh session on every sign-in (no session fixation).
	_ = s.Sessions.Delete(ctx, UserRealm, CookieValue(r, UserCookie))
	token, _, err := s.Sessions.Create(ctx, UserRealm, map[string]any{"user": user}, time.Duration(s.Cfg.UserSessionTTLSeconds)*time.Second)
	if err != nil {
		return err
	}
	SetUserCookie(w, token, s.Cfg.UserSessionTTLSeconds, s.Cfg.AuthCookieSecure)
	s.rememberUser(ctx, identity, user["id"].(string))
	httpx.LoggerFrom(ctx).Info("user signed in", "user_id", user["id"])
	httpx.JSON(w, 200, map[string]any{"user": user})
	return nil
}

func ptrOrNil(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

func (s *Service) rememberUser(ctx context.Context, identity *GoogleIdentity, userID string) {
	if !s.History.Enabled() {
		return
	}
	c, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	err := s.History.RememberUser(c, userID, bson.M{
		"google_sub":    identity.Subject,
		"email":         identity.Email,
		"name":          ptrOrNil(identity.Name),
		"avatar_url":    ptrOrNil(identity.Picture),
		"hosted_domain": ptrOrNil(identity.HostedDomain),
	})
	if err != nil {
		httpx.LoggerFrom(ctx).Warn("could not store user profile", "user_id", userID)
	}
}

func (s *Service) Me(w http.ResponseWriter, r *http.Request) error {
	session, err := s.CurrentUser(r)
	if err != nil {
		return err
	}
	httpx.JSON(w, 200, map[string]any{"user": session["user"]})
	return nil
}

func (s *Service) Logout(w http.ResponseWriter, r *http.Request) error {
	_ = s.Sessions.Delete(r.Context(), UserRealm, CookieValue(r, UserCookie))
	ClearUserCookie(w, s.Cfg.AuthCookieSecure)
	httpx.NoContent(w)
	return nil
}

func (s *Service) AdminLogin(w http.ResponseWriter, r *http.Request) error {
	body, _, err := httpx.DecodeJSON(r, 64<<10)
	errs := &httpx.ValidationError{}
	var username, password string
	switch {
	case err != nil:
		typ, msg := httpx.MsgJSONInvalid()
		errs.Add([]any{"body", 0}, typ, msg)
	case body == nil:
		typ, msg := httpx.MsgMissing()
		errs.Add([]any{"body"}, typ, msg)
	default:
		username = stringField(body, "username", 1, 128, errs)
		password = stringField(body, "password", 1, 512, errs)
	}
	if !errs.Empty() {
		return errs
	}
	if !s.Cfg.AdminEnabled() {
		return httpx.NewError(503, "admin_disabled", "Admin portal is disabled.")
	}
	ctx := r.Context()
	keys := []string{"ip:" + ClientKey(r), "user:" + strings.ToLower(strings.TrimSpace(username))}
	for _, k := range keys {
		if s.AdminFailures.Blocked(ctx, k) {
			return httpx.NewError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.")
		}
	}
	if !CheckAdminCredentials(s.Cfg.AdminUsername, s.Cfg.AdminPasswordHash, s.Cfg.AdminPassword, username, password) {
		for _, k := range keys {
			s.AdminFailures.Fail(ctx, k)
		}
		// Never log the password or the submitted username.
		httpx.LoggerFrom(ctx).Warn("admin sign-in failed", "client", ClientKey(r))
		select {
		case <-time.After(s.FailedLoginDelay):
		case <-ctx.Done():
		}
		return httpx.NewError(401, "invalid_credentials", "Incorrect username or password.")
	}
	for _, k := range keys {
		s.AdminFailures.Reset(ctx, k)
	}
	_ = s.Sessions.Delete(ctx, AdminRealm, CookieValue(r, AdminCookie))
	token, session, err := s.Sessions.Create(ctx, AdminRealm, map[string]any{"admin": AdminIdentity(s.Cfg.AdminUsername)}, time.Duration(s.Cfg.AdminSessionTTLSeconds)*time.Second)
	if err != nil {
		return err
	}
	SetAdminCookie(w, token, s.Cfg.AdminSessionTTLSeconds, s.Cfg.AuthCookieSecure)
	httpx.LoggerFrom(ctx).Info("admin signed in", "client", ClientKey(r))
	httpx.JSON(w, 200, map[string]any{"admin": session["admin"], "expires_at": session["expires_at"]})
	return nil
}

func (s *Service) AdminMe(w http.ResponseWriter, r *http.Request) error {
	session, err := s.CurrentAdmin(r)
	if err != nil {
		return err
	}
	httpx.JSON(w, 200, map[string]any{"admin": session["admin"], "expires_at": session["expires_at"]})
	return nil
}

func (s *Service) AdminLogout(w http.ResponseWriter, r *http.Request) error {
	_ = s.Sessions.Delete(r.Context(), AdminRealm, CookieValue(r, AdminCookie))
	ClearAdminCookie(w, s.Cfg.AuthCookieSecure)
	httpx.NoContent(w)
	return nil
}

func stringField(body map[string]any, key string, min, max int, errs *httpx.ValidationError) string {
	value, present, ok := httpx.BodyString(body, key)
	switch {
	case !present:
		typ, msg := httpx.MsgMissing()
		errs.Add([]any{"body", key}, typ, msg)
	case !ok:
		typ, msg := httpx.MsgStringType()
		errs.Add([]any{"body", key}, typ, msg)
	case len([]rune(value)) < min:
		typ, msg := httpx.MsgTooShort(min)
		errs.Add([]any{"body", key}, typ, msg)
	case len([]rune(value)) > max:
		typ, msg := httpx.MsgTooLong(max)
		errs.Add([]any{"body", key}, typ, msg)
	}
	return value
}
