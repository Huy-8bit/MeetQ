// Package platform holds small helpers that reproduce Python gateway conventions
// exactly (timestamp strings, IDs), so data written by Go and Python is identical.
package platform

import (
	"crypto/rand"
	"encoding/hex"
	"strings"
	"time"
)

// NowUTC is the clock used everywhere; tests may replace it.
var NowUTC = func() time.Time { return time.Now().UTC() }

// ISO renders a time like Python's `dt.astimezone(utc).isoformat().replace("+00:00", "Z")`:
// microsecond precision, and no fractional part at all when microseconds are zero.
func ISO(t time.Time) string {
	t = t.UTC()
	micros := t.Nanosecond() / 1000
	if micros == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05") + "." + pad6(micros) + "Z"
}

// ISOPtr returns nil for zero/nil times (Python `iso(None) -> None`).
func ISOPtr(t *time.Time) *string {
	if t == nil || t.IsZero() {
		return nil
	}
	s := ISO(*t)
	return &s
}

// NowStr is `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`.
func NowStr() string { return ISO(NowUTC()) }

func pad6(v int) string {
	s := "000000" + itoa(v)
	return s[len(s)-6:]
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	var buf [20]byte
	i := len(buf)
	for v > 0 {
		i--
		buf[i] = byte('0' + v%10)
		v /= 10
	}
	return string(buf[i:])
}

// ParseTime mirrors `datetime.fromisoformat(value.replace("Z", "+00:00"))`; naive
// values are treated as UTC. Returns nil when the value is not a timestamp.
func ParseTime(value string) *time.Time {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil
	}
	value = strings.Replace(value, "Z", "+00:00", 1)
	layouts := []string{
		"2006-01-02T15:04:05.999999999-07:00",
		"2006-01-02T15:04:05-07:00",
		"2006-01-02T15:04:05.999999999",
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05.999999999-07:00",
		"2006-01-02 15:04:05-07:00",
		"2006-01-02 15:04:05.999999999",
		"2006-01-02 15:04:05",
		"2006-01-02",
	}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, value); err == nil {
			utc := t.UTC()
			return &utc
		}
	}
	return nil
}

// GenerateID is `f"{prefix}_{uuid.uuid4().hex[:12]}"`.
func GenerateID(prefix string) string {
	return prefix + "_" + RandomHex(12)
}

// RandomHex returns n lowercase hex characters.
func RandomHex(n int) string {
	buf := make([]byte, (n+1)/2)
	if _, err := rand.Read(buf); err != nil {
		panic(err)
	}
	return hex.EncodeToString(buf)[:n]
}
