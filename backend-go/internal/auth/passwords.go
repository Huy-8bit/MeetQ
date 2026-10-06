package auth

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"golang.org/x/crypto/scrypt"
)

// VerifyScrypt checks the Python admin hash format
// "scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>" (server/service/auth/passwords.py).
func VerifyScrypt(password, encoded string) bool {
	parts := strings.Split(strings.TrimSpace(encoded), "$")
	if len(parts) != 6 || parts[0] != "scrypt" {
		return false
	}
	n, err1 := strconv.Atoi(parts[1])
	r, err2 := strconv.Atoi(parts[2])
	p, err3 := strconv.Atoi(parts[3])
	salt, err4 := base64.StdEncoding.DecodeString(parts[4])
	expected, err5 := base64.StdEncoding.DecodeString(parts[5])
	if err1 != nil || err2 != nil || err3 != nil || err4 != nil || err5 != nil || len(expected) == 0 {
		return false
	}
	// Same 64 MiB memory ceiling as Python's maxmem.
	if 128*int64(r)*int64(n) > 64*1024*1024 {
		return false
	}
	digest, err := scrypt.Key([]byte(password), salt, n, r, p, len(expected))
	if err != nil {
		return false
	}
	return subtle.ConstantTimeCompare(digest, expected) == 1
}

// AdminIdentity mirrors api._admin_identity.
func AdminIdentity(username string) map[string]any {
	username = strings.TrimSpace(username)
	sum := sha256.Sum256([]byte("admin:" + username))
	return map[string]any{
		"id":           "adm_" + hex.EncodeToString(sum[:])[:12],
		"username":     username,
		"display_name": username,
	}
}

// GoogleUserID mirrors api._user_id: stable per Google account (`sub`).
func GoogleUserID(subject string) string {
	sum := sha256.Sum256([]byte("google:" + subject))
	return "usr_" + hex.EncodeToString(sum[:])[:20]
}

// CheckAdminCredentials mirrors api._check_admin_credentials (constant-time compares).
func CheckAdminCredentials(expectedUser, passwordHash, plainPassword, username, password string) bool {
	userOK := subtle.ConstantTimeCompare([]byte(strings.TrimSpace(expectedUser)), []byte(strings.TrimSpace(username))) == 1
	var passwordOK bool
	if passwordHash != "" {
		passwordOK = VerifyScrypt(password, passwordHash)
	} else {
		passwordOK = subtle.ConstantTimeCompare([]byte(strings.TrimSpace(plainPassword)), []byte(password)) == 1
	}
	return userOK && passwordOK
}

// RateLimiter counts failures per key in Redis, so every Go instance shares the
// limit (the Python gateway keeps the same thresholds per process in memory).
type RateLimiter struct {
	R           *redis.Client
	Scope       string
	MaxFailures int
	Window      time.Duration
}

func (l *RateLimiter) key(k string) string {
	sum := sha256.Sum256([]byte(k))
	return "brseai:v1:go:loginfail:" + l.Scope + ":" + hex.EncodeToString(sum[:16])
}

func (l *RateLimiter) Blocked(ctx context.Context, k string) bool {
	n, err := l.R.Get(ctx, l.key(k)).Int()
	return err == nil && n >= l.MaxFailures
}

func (l *RateLimiter) Fail(ctx context.Context, k string) {
	key := l.key(k)
	pipe := l.R.Pipeline()
	pipe.Incr(ctx, key)
	pipe.ExpireNX(ctx, key, l.Window)
	_, _ = pipe.Exec(ctx)
}

func (l *RateLimiter) Reset(ctx context.Context, k string) {
	_ = l.R.Del(ctx, l.key(k)).Err()
}
