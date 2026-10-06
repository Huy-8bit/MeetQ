package httpx

import (
	"context"
	"log/slog"
	"net/http"
	"regexp"
	"runtime/debug"
	"slices"
	"strconv"
	"strings"
	"time"

	"meetq/backend-go/internal/platform"
)

type ctxKey int

const (
	requestIDKey ctxKey = iota
	loggerKey
	routeFieldsKey
)

var requestIDPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{6,80}$`)

// RequestID propagates an incoming X-Request-ID (when well-formed) or creates one,
// exposes it on the response and on a request-scoped logger.
func RequestID(base *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			id := r.Header.Get("X-Request-ID")
			if !requestIDPattern.MatchString(id) {
				id = "req_" + platform.RandomHex(12)
			}
			w.Header().Set("X-Request-ID", id)
			ctx := context.WithValue(r.Context(), requestIDKey, id)
			ctx = context.WithValue(ctx, loggerKey, base.With("request_id", id))
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func RequestIDFrom(ctx context.Context) string {
	id, _ := ctx.Value(requestIDKey).(string)
	return id
}

func LoggerFrom(ctx context.Context) *slog.Logger {
	if l, ok := ctx.Value(loggerKey).(*slog.Logger); ok {
		return l
	}
	return slog.Default()
}

// routeFields lets handlers attach safe identifiers (room_id, meeting_id, user_id) to the access log.
type routeFields struct{ attrs []any }

func AddLogFields(ctx context.Context, attrs ...any) {
	if f, ok := ctx.Value(routeFieldsKey).(*routeFields); ok {
		f.attrs = append(f.attrs, attrs...)
	}
}

type statusRecorder struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (s *statusRecorder) WriteHeader(code int) {
	if s.status == 0 {
		s.status = code
	}
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	if s.status == 0 {
		s.status = http.StatusOK
	}
	n, err := s.ResponseWriter.Write(b)
	s.bytes += n
	return n, err
}

// Unwrap lets http.ResponseController / websocket hijacking reach the real writer.
func (s *statusRecorder) Unwrap() http.ResponseWriter { return s.ResponseWriter }

// AccessLog writes one structured line per request. Query strings are never logged
// (they can carry search terms); neither are bodies, cookies or tokens.
func AccessLog(observe func(method, route string, status int, d time.Duration)) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			started := time.Now()
			fields := &routeFields{}
			rec := &statusRecorder{ResponseWriter: w}
			ctx := context.WithValue(r.Context(), routeFieldsKey, fields)
			next.ServeHTTP(rec, r.WithContext(ctx))
			if rec.status == 0 {
				rec.status = http.StatusOK
			}
			duration := time.Since(started)
			route := RoutePattern(r)
			if observe != nil {
				observe(r.Method, route, rec.status, duration)
			}
			attrs := append([]any{
				"method", r.Method,
				"path", r.URL.Path,
				"route", route,
				"status", rec.status,
				"duration_ms", duration.Milliseconds(),
			}, fields.attrs...)
			level := slog.LevelInfo
			if rec.status >= 500 {
				level = slog.LevelError
			}
			LoggerFrom(r.Context()).Log(r.Context(), level, "http_request", attrs...)
		})
	}
}

// RoutePatternFunc is set by the router package (chi) to return the matched pattern.
var RoutePatternFunc = func(r *http.Request) string { return "" }

func RoutePattern(r *http.Request) string {
	if p := RoutePatternFunc(r); p != "" {
		return p
	}
	return "unmatched"
}

// Recover turns panics into 500s without leaking stack traces to clients.
func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if v := recover(); v != nil {
				if v == http.ErrAbortHandler {
					panic(v)
				}
				LoggerFrom(r.Context()).Error("panic", "panic", v, "stack", string(debug.Stack()))
				w.Header().Set("Content-Type", "text/plain; charset=utf-8")
				w.WriteHeader(http.StatusInternalServerError)
				_, _ = w.Write([]byte("Internal Server Error"))
			}
		}()
		next.ServeHTTP(w, r)
	})
}

var unsafeMethods = map[string]bool{"POST": true, "PUT": true, "PATCH": true, "DELETE": true}

// OriginCheck is the CSRF guard for cookie sessions (Python: reject_untrusted_origin).
// Requests without Origin (curl, server-to-server) are allowed; SameSite adds a second layer.
func OriginCheck(allowed []string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if unsafeMethods[r.Method] && strings.HasPrefix(r.URL.Path, "/api/") {
				if origin, ok := r.Header["Origin"]; ok && len(origin) > 0 {
					if !slices.Contains(allowed, strings.TrimRight(origin[0], "/")) {
						JSON(w, http.StatusForbidden, Envelope("origin_not_allowed", "Request origin is not allowed.", nil))
						return
					}
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}

var corsMethods = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT, QUERY"

// CORS mirrors Starlette's CORSMiddleware(allow_origins=list, allow_credentials=True,
// allow_methods=["*"], allow_headers=["*"]): exact origins only, never "*".
func CORS(allowed []string) func(http.Handler) http.Handler {
	isAllowed := func(origin string) bool { return slices.Contains(allowed, origin) }
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")
			if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
				h := w.Header()
				h.Set("Vary", "Origin, Access-Control-Request-Method, Access-Control-Request-Headers, Access-Control-Request-Private-Network")
				h.Set("Access-Control-Allow-Methods", corsMethods)
				h.Set("Access-Control-Max-Age", "600")
				h.Set("Access-Control-Allow-Credentials", "true")
				if requested := r.Header.Get("Access-Control-Request-Headers"); requested != "" {
					h.Set("Access-Control-Allow-Headers", requested)
				}
				if !isAllowed(origin) {
					h.Set("Content-Type", "text/plain; charset=utf-8")
					h.Set("Content-Length", strconv.Itoa(len("Disallowed CORS origin")))
					w.WriteHeader(http.StatusBadRequest)
					_, _ = w.Write([]byte("Disallowed CORS origin"))
					return
				}
				h.Set("Access-Control-Allow-Origin", origin)
				h.Set("Content-Type", "text/plain; charset=utf-8")
				h.Set("Content-Length", "2")
				w.WriteHeader(http.StatusOK)
				_, _ = w.Write([]byte("OK"))
				return
			}
			if origin != "" {
				h := w.Header()
				h.Set("Access-Control-Allow-Credentials", "true")
				h.Add("Vary", "Origin")
				if isAllowed(origin) {
					h.Set("Access-Control-Allow-Origin", origin)
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}

// WithTimeout bounds a request's context (DB, AI, S3 calls inherit it).
func WithTimeout(d time.Duration) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if d <= 0 || strings.HasPrefix(r.URL.Path, "/ws/") {
				next.ServeHTTP(w, r)
				return
			}
			ctx, cancel := context.WithTimeout(r.Context(), d)
			defer cancel()
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}
