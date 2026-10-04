import { describe, expect, it } from "vitest";
import { loginPathFor, safeNextPath } from "./next";

describe("safeNextPath", () => {
  it.each([
    ["/rooms/rm_abc123", "/rooms/rm_abc123"],
    ["/rooms/rm_abc123?tab=chat#x", "/rooms/rm_abc123?tab=chat#x"],
    ["/test", "/test"],
    ["/", "/"],
  ])("keeps internal path %s", (raw, expected) => {
    expect(safeNextPath(raw)).toBe(expected);
  });

  it.each([
    null,
    "",
    "https://evil.com",
    "//evil.com",
    "/\\evil.com",
    "/\t/evil.com",
    "javascript:alert(1)",
    "rooms/rm_1",
    "/login",
    "/admin",
    "/admin/meetings",
  ])("falls back to / for %s", (raw) => {
    expect(safeNextPath(raw)).toBe("/");
  });

  it("builds the login URL that preserves an invite", () => {
    expect(loginPathFor("/rooms/rm_abc123")).toBe("/login?next=%2Frooms%2Frm_abc123");
    expect(loginPathFor("/")).toBe("/login");
  });
});
