package auth

import (
	"context"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const googleJWKSURL = "https://www.googleapis.com/oauth2/v3/certs"

var maxAgeRe = regexp.MustCompile(`max-age=(\d+)`)

// GoogleTokenError: the credential is not a valid Google ID token for this app.
type GoogleTokenError struct{ Reason string }

func (e *GoogleTokenError) Error() string { return "google token rejected: " + e.Reason }

var ErrAccountNotAllowed = errors.New("account not allowed")

type GoogleIdentity struct {
	Subject      string
	Email        string
	Name         *string
	Picture      *string
	HostedDomain *string
}

type jwk struct {
	Kid string `json:"kid"`
	Kty string `json:"kty"`
	N   string `json:"n"`
	E   string `json:"e"`
}

// GoogleVerifier mirrors server/service/auth/google.py.
type GoogleVerifier struct {
	ClientID       string
	AllowedDomains map[string]bool
	JWKSURL        string
	HTTP           *http.Client

	mu        sync.Mutex
	keys      map[string]*rsa.PublicKey
	expiresAt time.Time
}

func NewGoogleVerifier(clientID, allowedDomains string) *GoogleVerifier {
	domains := map[string]bool{}
	for _, d := range strings.Split(allowedDomains, ",") {
		if d = strings.ToLower(strings.TrimSpace(d)); d != "" {
			domains[d] = true
		}
	}
	return &GoogleVerifier{
		ClientID:       clientID,
		AllowedDomains: domains,
		JWKSURL:        googleJWKSURL,
		HTTP:           &http.Client{Timeout: 5 * time.Second},
	}
}

func (v *GoogleVerifier) fetch(ctx context.Context) (map[string]*rsa.PublicKey, time.Duration, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, v.JWKSURL, nil)
	if err != nil {
		return nil, 0, err
	}
	resp, err := v.HTTP.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, 0, fmt.Errorf("jwks status %d", resp.StatusCode)
	}
	var body struct {
		Keys []jwk `json:"keys"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, 0, err
	}
	ttl := time.Hour
	if m := maxAgeRe.FindStringSubmatch(resp.Header.Get("Cache-Control")); m != nil {
		if secs, err := strconv.Atoi(m[1]); err == nil {
			ttl = time.Duration(secs) * time.Second
		}
	}
	keys := map[string]*rsa.PublicKey{}
	for _, k := range body.Keys {
		if k.Kty != "RSA" {
			continue
		}
		n, err1 := base64.RawURLEncoding.DecodeString(k.N)
		e, err2 := base64.RawURLEncoding.DecodeString(k.E)
		if err1 != nil || err2 != nil {
			continue
		}
		keys[k.Kid] = &rsa.PublicKey{N: new(big.Int).SetBytes(n), E: int(new(big.Int).SetBytes(e).Int64())}
	}
	return keys, ttl, nil
}

func (v *GoogleVerifier) key(ctx context.Context, kid string) (*rsa.PublicKey, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	for _, force := range []bool{false, true} { // refetch once: Google rotates keys
		if force || v.keys == nil || time.Now().After(v.expiresAt) {
			keys, ttl, err := v.fetch(ctx)
			if err != nil {
				return nil, err
			}
			if ttl < time.Minute {
				ttl = time.Minute
			}
			v.keys, v.expiresAt = keys, time.Now().Add(ttl)
		}
		if k, ok := v.keys[kid]; ok {
			return k, nil
		}
	}
	return nil, &GoogleTokenError{Reason: "unknown_signing_key"}
}

func (v *GoogleVerifier) Verify(ctx context.Context, credential string) (*GoogleIdentity, error) {
	parser := jwt.NewParser(jwt.WithValidMethods([]string{"RS256"}), jwt.WithAudience(v.ClientID), jwt.WithExpirationRequired())
	unverified, _, err := jwt.NewParser().ParseUnverified(credential, jwt.MapClaims{})
	if err != nil {
		return nil, &GoogleTokenError{Reason: "malformed_token"}
	}
	if alg, _ := unverified.Header["alg"].(string); alg != "RS256" {
		return nil, &GoogleTokenError{Reason: "unexpected_algorithm"}
	}
	kid, _ := unverified.Header["kid"].(string)
	publicKey, err := v.key(ctx, kid)
	if err != nil {
		return nil, err
	}
	claims := jwt.MapClaims{}
	if _, err := parser.ParseWithClaims(credential, claims, func(*jwt.Token) (any, error) { return publicKey, nil }); err != nil {
		if errors.Is(err, jwt.ErrTokenExpired) {
			return nil, &GoogleTokenError{Reason: "expired"}
		}
		return nil, &GoogleTokenError{Reason: "invalid_signature_or_claims"}
	}
	iss, _ := claims["iss"].(string)
	if iss != "accounts.google.com" && iss != "https://accounts.google.com" {
		return nil, &GoogleTokenError{Reason: "unexpected_issuer"}
	}
	switch verified := claims["email_verified"].(type) {
	case bool:
		if !verified {
			return nil, &GoogleTokenError{Reason: "email_not_verified"}
		}
	case string:
		if verified != "true" {
			return nil, &GoogleTokenError{Reason: "email_not_verified"}
		}
	default:
		return nil, &GoogleTokenError{Reason: "email_not_verified"}
	}
	subject := fmt.Sprint(valueOr(claims["sub"], ""))
	email := strings.ToLower(strings.TrimSpace(fmt.Sprint(valueOr(claims["email"], ""))))
	if subject == "" || email == "" {
		return nil, &GoogleTokenError{Reason: "missing_identity"}
	}
	var hosted *string
	if hd, _ := claims["hd"].(string); hd != "" {
		lowered := strings.ToLower(hd)
		hosted = &lowered
	}
	if len(v.AllowedDomains) > 0 {
		domain := email[strings.LastIndex(email, "@")+1:]
		if !v.AllowedDomains[domain] && (hosted == nil || !v.AllowedDomains[*hosted]) {
			return nil, ErrAccountNotAllowed
		}
	}
	return &GoogleIdentity{
		Subject:      subject,
		Email:        email,
		Name:         optionalClaim(claims, "name"),
		Picture:      optionalClaim(claims, "picture"),
		HostedDomain: hosted,
	}, nil
}

func valueOr(v any, fallback any) any {
	if v == nil {
		return fallback
	}
	return v
}

func optionalClaim(claims jwt.MapClaims, key string) *string {
	if s, _ := claims[key].(string); s != "" {
		return &s
	}
	return nil
}
