package room

import (
	"os/exec"
	"testing"
)

// Cross-checks Argon2 hashes with the Python implementation when the BE venv exists.
func TestArgon2CompatibleWithPython(t *testing.T) {
	python := "../../../BE/.venv/bin/python"
	goHash, err := HashPassword("blue-river-42")
	if err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command(python, "-c", `import sys
from argon2 import PasswordHasher
ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)
print(ph.verify(sys.argv[1], "blue-river-42"))
print(ph.hash("blue-river-42"))`, goHash).Output()
	if err != nil {
		t.Skipf("python venv unavailable: %v", err)
	}
	lines := splitLines(string(out))
	if lines[0] != "True" {
		t.Fatalf("python could not verify the Go hash: %q", out)
	}
	if !VerifyPassword("blue-river-42", lines[1]) {
		t.Fatalf("Go could not verify the Python hash %q", lines[1])
	}
	if VerifyPassword("blue-river-43", lines[1]) {
		t.Fatal("wrong password accepted")
	}
}

func splitLines(s string) []string {
	var out []string
	cur := ""
	for _, r := range s {
		if r == '\n' {
			out = append(out, cur)
			cur = ""
			continue
		}
		cur += string(r)
	}
	if cur != "" {
		out = append(out, cur)
	}
	return out
}
