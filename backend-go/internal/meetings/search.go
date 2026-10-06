package meetings

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

const (
	SearchMinLength = 2
	SearchMaxLength = 100
	SnippetContext  = 70
)

func isWide(text string) bool {
	for _, r := range text {
		if r >= 0x2E80 {
			return true
		}
	}
	return false
}

func NormalizeQuery(raw string) (string, error) {
	fields := strings.Fields(raw)
	combined := strings.Join(fields, " ")
	query := norm.NFC.String(combined)
	if len([]rune(query)) > SearchMaxLength {
		return "", fmt.Errorf("Search terms must be at most %d characters.", SearchMaxLength)
	}
	if len([]rune(query)) < SearchMinLength && !(len([]rune(query)) > 0 && isWide(query)) {
		return "", fmt.Errorf("Enter at least %d characters to search.", SearchMinLength)
	}
	return query, nil
}

func CompileQuery(query string) (*regexp.Regexp, error) {
	escaped := regexp.QuoteMeta(query)
	return regexp.Compile("(?i)" + escaped)
}

func Snippet(text string, pattern *regexp.Regexp) (string, [][]int) {
	normalized := norm.NFC.String(text)
	loc := pattern.FindStringIndex(normalized)
	if loc == nil {
		runes := []rune(normalized)
		cutLen := SnippetContext * 2
		if len(runes) > cutLen {
			return string(runes[:cutLen]) + "…", [][]int{}
		}
		return normalized, [][]int{}
	}

	start := loc[0] - SnippetContext
	if start < 0 {
		start = 0
	}
	end := loc[1] + SnippetContext
	if end > len(normalized) {
		end = len(normalized)
	}

	if start > 0 {
		spaceIdx := strings.Index(normalized[start:loc[0]], " ")
		if spaceIdx >= 0 {
			start = start + spaceIdx + 1
		}
	}

	window := normalized[start:end]
	prefix := ""
	if start > 0 {
		prefix = "…"
	}
	suffix := ""
	if end < len(normalized) {
		suffix = "…"
	}

	offset := len(prefix)
	matches := pattern.FindAllStringIndex(window, -1)
	highlights := make([][]int, 0, len(matches))
	for _, m := range matches {
		highlights = append(highlights, []int{m[0] + offset, m[1] + offset})
	}

	return prefix + window + suffix, highlights
}

// Dummy unicode import
var _ = unicode.IsLetter
