package httpx

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

// FieldError is one pydantic-style validation error.
type FieldError struct {
	Loc  []any
	Msg  string
	Type string
}

// ValidationError reproduces the Python gateway's RequestValidationError handler
// (BE/server/service/gateway/main.py): language errors -> invalid_language,
// password errors -> invalid_room_password_setting, everything else ->
// invalid_request with details.errors. Submitted values are never echoed.
type ValidationError struct {
	Errors []FieldError
}

func (e *ValidationError) Error() string { return "validation error" }

func (e *ValidationError) Add(loc []any, typ, msg string) {
	e.Errors = append(e.Errors, FieldError{Loc: loc, Msg: msg, Type: typ})
}

func (e *ValidationError) Empty() bool { return len(e.Errors) == 0 }

func (e *ValidationError) OrNil() error {
	if e.Empty() {
		return nil
	}
	return e
}

func (e *ValidationError) Render(w http.ResponseWriter) {
	for _, item := range e.Errors {
		for _, part := range item.Loc {
			if s, ok := part.(string); ok && s == "language" {
				JSON(w, 422, map[string]any{"error": map[string]any{
					"code": "invalid_language", "message": item.Msg, "details": map[string]any{"field": "language"},
				}})
				return
			}
		}
	}
	safe := make([]map[string]any, 0, len(e.Errors))
	for _, item := range e.Errors {
		msg := strings.TrimPrefix(item.Msg, "Value error, ")
		loc := item.Loc
		if loc == nil {
			loc = []any{}
		}
		safe = append(safe, map[string]any{"loc": loc, "msg": msg, "type": item.Type})
	}
	for _, item := range safe {
		hasPassword := false
		for _, part := range item["loc"].([]any) {
			if s, ok := part.(string); ok && s == "password" {
				hasPassword = true
			}
		}
		if hasPassword || strings.Contains(strings.ToLower(item["msg"].(string)), "password") {
			JSON(w, 422, map[string]any{"error": map[string]any{
				"code": "invalid_room_password_setting", "message": item["msg"], "details": map[string]any{"field": "password"},
			}})
			return
		}
	}
	JSON(w, 422, map[string]any{"error": map[string]any{
		"code": "invalid_request", "message": "Validation error", "details": map[string]any{"errors": safe},
	}})
}

// ── Pydantic message builders ─────────────────────────────────────────────

func MsgMissing() (string, string) { return "missing", "Field required" }

func MsgStringType() (string, string) { return "string_type", "Input should be a valid string" }

func MsgBoolType() (string, string) { return "bool_type", "Input should be a valid boolean" }

func MsgDictType() (string, string) {
	return "model_attributes_type", "Input should be a valid dictionary or object to extract fields from"
}

func MsgListType() (string, string) { return "list_type", "Input should be a valid list" }

func MsgTooShort(min int) (string, string) {
	return "string_too_short", fmt.Sprintf("String should have at least %d character%s", min, plural(min))
}

func MsgTooLong(max int) (string, string) {
	return "string_too_long", fmt.Sprintf("String should have at most %d character%s", max, plural(max))
}

func MsgLiteral(options []string) (string, string) {
	quoted := make([]string, len(options))
	for i, o := range options {
		quoted[i] = "'" + o + "'"
	}
	var text string
	if len(quoted) == 1 {
		text = quoted[0]
	} else {
		text = strings.Join(quoted[:len(quoted)-1], ", ") + " or " + quoted[len(quoted)-1]
	}
	return "literal_error", "Input should be " + text
}

func MsgIntParsing() (string, string) {
	return "int_parsing", "Input should be a valid integer, unable to parse string as an integer"
}

func MsgIntType() (string, string) { return "int_type", "Input should be a valid integer" }

func MsgGE(v int) (string, string) {
	return "greater_than_equal", fmt.Sprintf("Input should be greater than or equal to %d", v)
}

func MsgLE(v int) (string, string) {
	return "less_than_equal", fmt.Sprintf("Input should be less than or equal to %d", v)
}

func MsgPattern(pattern string) (string, string) {
	return "string_pattern_mismatch", fmt.Sprintf("String should match pattern '%s'", pattern)
}

func MsgValue(message string) (string, string) { return "value_error", "Value error, " + message }

func MsgJSONInvalid() (string, string) { return "json_invalid", "JSON decode error" }

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// ── Body field accessors (pydantic lax mode for the types the API uses) ──

// BodyString returns (value, present, ok). Pydantic strict-ish: only JSON strings are strings.
func BodyString(body map[string]any, key string) (string, bool, bool) {
	raw, present := body[key]
	if !present {
		return "", false, true
	}
	if raw == nil {
		return "", true, false
	}
	s, ok := raw.(string)
	return s, true, ok
}

// BodyBool follows pydantic's lax bool parsing.
func BodyBool(body map[string]any, key string) (bool, bool, bool) {
	raw, present := body[key]
	if !present {
		return false, false, true
	}
	switch v := raw.(type) {
	case bool:
		return v, true, true
	case json.Number:
		if v.String() == "1" {
			return true, true, true
		}
		if v.String() == "0" {
			return false, true, true
		}
	case string:
		switch strings.ToLower(v) {
		case "1", "on", "t", "true", "y", "yes":
			return true, true, true
		case "0", "off", "f", "false", "n", "no":
			return false, true, true
		}
	}
	return false, true, false
}

// BodyInt follows pydantic's lax int parsing (integers, integral floats, numeric strings).
func BodyInt(body map[string]any, key string) (int, bool, string) {
	raw, present := body[key]
	if !present {
		return 0, false, ""
	}
	switch v := raw.(type) {
	case json.Number:
		if i, err := v.Int64(); err == nil {
			return int(i), true, ""
		}
		if f, err := v.Float64(); err == nil && f == math.Trunc(f) {
			return int(f), true, ""
		}
		return 0, true, "int_from_float"
	case string:
		if i, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			return i, true, ""
		}
		return 0, true, "int_parsing"
	case bool:
		return 0, true, "int_type"
	case nil:
		return 0, true, "int_type"
	}
	return 0, true, "int_type"
}

// ── Query parameters ──────────────────────────────────────────────────────

type QueryInt struct {
	Name     string
	Default  int
	Min, Max *int
}

func Ptr[T any](v T) *T { return &v }

// Int parses a query int like FastAPI Query(default, ge=, le=).
func (q QueryInt) Parse(values url.Values, errs *ValidationError) int {
	raw, ok := values[q.Name]
	if !ok || len(raw) == 0 {
		return q.Default
	}
	text := raw[len(raw)-1]
	v, err := strconv.Atoi(strings.TrimSpace(text))
	if err != nil {
		typ, msg := MsgIntParsing()
		errs.Add([]any{"query", q.Name}, typ, msg)
		return q.Default
	}
	if q.Min != nil && v < *q.Min {
		typ, msg := MsgGE(*q.Min)
		errs.Add([]any{"query", q.Name}, typ, msg)
	}
	if q.Max != nil && v > *q.Max {
		typ, msg := MsgLE(*q.Max)
		errs.Add([]any{"query", q.Name}, typ, msg)
	}
	return v
}

// QueryString returns the last value (FastAPI semantics) and whether it was given.
func QueryString(values url.Values, name string) (string, bool) {
	raw, ok := values[name]
	if !ok || len(raw) == 0 {
		return "", false
	}
	return raw[len(raw)-1], true
}

// QueryPattern validates an optional string against a regex (FastAPI pattern=).
func QueryPattern(values url.Values, name, pattern string, maxLen int, errs *ValidationError) (string, bool) {
	value, ok := QueryString(values, name)
	if !ok {
		return "", false
	}
	if maxLen > 0 && len([]rune(value)) > maxLen {
		typ, msg := MsgTooLong(maxLen)
		errs.Add([]any{"query", name}, typ, msg)
		return value, true
	}
	if pattern != "" && !regexp.MustCompile(pattern).MatchString(value) {
		typ, msg := MsgPattern(pattern)
		errs.Add([]any{"query", name}, typ, msg)
	}
	return value, true
}

// QueryBool parses FastAPI bool query params.
func QueryBool(values url.Values, name string, def bool, errs *ValidationError) bool {
	value, ok := QueryString(values, name)
	if !ok {
		return def
	}
	switch strings.ToLower(value) {
	case "1", "on", "t", "true", "y", "yes":
		return true
	case "0", "off", "f", "false", "n", "no":
		return false
	}
	typ, msg := MsgBoolType()
	errs.Add([]any{"query", name}, typ, msg)
	return def
}
