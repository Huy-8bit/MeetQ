package room

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"golang.org/x/crypto/argon2"

	"meetq/backend-go/internal/store"
)

const (
	PasswordMinLength     = 6
	PasswordMaxLength     = 128
	passwordMaxFailures   = 10
	passwordFailureWindow = 600 * time.Second
	argonTime             = 2
	argonMemoryKiB        = 19456
	argonThreads          = 1
	argonKeyLen           = 32
	argonSaltLen          = 16
)

var (
	ErrPasswordRequired = errors.New("room password required")
	ErrInvalidPassword  = errors.New("invalid room password")
)

type PasswordRateLimitedError struct{ RetryAfter int }

func (e *PasswordRateLimitedError) Error() string { return "too many incorrect room passwords" }

// HashPassword produces the same PHC string as argon2-cffi's PasswordHasher
// (Argon2id, v=19, m=19456, t=2, p=1, 32-byte hash, 16-byte salt).
func HashPassword(password string) (string, error) {
	salt := make([]byte, argonSaltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	key := argon2.IDKey([]byte(password), salt, argonTime, argonMemoryKiB, argonThreads, argonKeyLen)
	enc := base64.RawStdEncoding
	return fmt.Sprintf("$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s", argon2.Version, argonMemoryKiB, argonTime, argonThreads, enc.EncodeToString(salt), enc.EncodeToString(key)), nil
}

// VerifyPassword accepts any argon2id/argon2i PHC hash (parameters read from the hash).
func VerifyPassword(password, encoded string) bool {
	if password == "" || len([]rune(password)) > PasswordMaxLength || encoded == "" {
		return false
	}
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || (parts[1] != "argon2id" && parts[1] != "argon2i") {
		return false
	}
	var version int
	if _, err := fmt.Sscanf(parts[2], "v=%d", &version); err != nil || version != argon2.Version {
		return false
	}
	var memory, iterations uint32
	var threads uint8
	for _, item := range strings.Split(parts[3], ",") {
		key, value, _ := strings.Cut(item, "=")
		n, err := strconv.ParseUint(value, 10, 32)
		if err != nil {
			return false
		}
		switch key {
		case "m":
			memory = uint32(n)
		case "t":
			iterations = uint32(n)
		case "p":
			threads = uint8(n)
		}
	}
	if memory == 0 || iterations == 0 || threads == 0 || memory > 1<<20 {
		return false
	}
	enc := base64.RawStdEncoding
	salt, err1 := enc.DecodeString(parts[4])
	expected, err2 := enc.DecodeString(parts[5])
	if err1 != nil || err2 != nil || len(expected) == 0 {
		return false
	}
	var key []byte
	if parts[1] == "argon2id" {
		key = argon2.IDKey([]byte(password), salt, iterations, memory, threads, uint32(len(expected)))
	} else {
		key = argon2.Key([]byte(password), salt, iterations, memory, threads, uint32(len(expected)))
	}
	return subtle.ConstantTimeCompare(key, expected) == 1
}

// AccessStore mirrors RoomAccessStore: the hash lives in room:{id}:access, never in room state.
type AccessStore struct {
	R   *redis.Client
	TTL time.Duration
}

func failureKeys(roomID, clientIP, userID string) []string {
	if clientIP == "" {
		clientIP = "unknown"
	}
	keys := []string{"room:" + roomID + ":pwfail:ip:" + clientIP}
	if userID != "" {
		keys = append(keys, "room:"+roomID+":pwfail:user:"+userID)
	}
	return keys
}

func (a *AccessStore) SetPassword(ctx context.Context, roomID, password string) error {
	encoded, err := HashPassword(password)
	if err != nil {
		return err
	}
	raw, _ := json.Marshal(map[string]string{"password_hash": encoded})
	return a.R.Set(ctx, store.AccessKey(roomID), raw, a.TTL).Err()
}

func (a *AccessStore) Delete(ctx context.Context, roomID string) error {
	return a.R.Del(ctx, store.AccessKey(roomID)).Err()
}

func (a *AccessStore) passwordHash(ctx context.Context, roomID string) string {
	raw, err := a.R.Get(ctx, store.AccessKey(roomID)).Bytes()
	if err != nil {
		return ""
	}
	var doc map[string]any
	if json.Unmarshal(raw, &doc) != nil {
		return ""
	}
	s, _ := doc["password_hash"].(string)
	return s
}

// CheckJoin mirrors check_join: rate limit first, then verify; failures count per IP and per user.
func (a *AccessStore) CheckJoin(ctx context.Context, roomID string, password *string, clientIP, userID string) error {
	keys := failureKeys(roomID, clientIP, userID)
	for _, key := range keys {
		n, err := a.R.Get(ctx, key).Int()
		if err == nil && n >= passwordMaxFailures {
			return &PasswordRateLimitedError{RetryAfter: int(passwordFailureWindow.Seconds())}
		}
	}
	if password == nil || *password == "" {
		return ErrPasswordRequired
	}
	encoded := a.passwordHash(ctx, roomID)
	if encoded != "" && VerifyPassword(*password, encoded) {
		if userID != "" {
			_ = a.R.Del(ctx, keys[len(keys)-1]).Err()
		}
		return nil
	}
	for _, key := range keys {
		count, err := a.R.Incr(ctx, key).Result()
		if err == nil && count == 1 {
			_ = a.R.Expire(ctx, key, passwordFailureWindow).Err()
		}
	}
	return ErrInvalidPassword
}
