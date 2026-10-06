import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { formatMeetingTitle, outranks, permissionsFor } from "../lib/roomRoles";
import type { ParticipantSnapshot } from "../types/api";
import { ParticipantList } from "./ParticipantList";
import { RoomSecurityPanel } from "./RoomSecurityPanel";

function person(id: string, name: string, role: ParticipantSnapshot["role"]): ParticipantSnapshot {
  return { participant_id: id, display_name: name, language: "vi", status: "connected", kind: "human", role };
}

const PEOPLE = [person("pt_huy", "Huy", "host"), person("pt_kenji", "Kenji", "co_host"), person("pt_tuan", "Tuan", "participant")];

function menuFor(name: string) {
  return screen.queryByRole("button", { name: `Actions for ${name}` });
}

describe("People panel", () => {
  it("shows real role badges", () => {
    render(<ParticipantList participants={PEOPLE} selfParticipantId="pt_tuan" selfRole="participant" permissions={permissionsFor("participant")} />);
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).getByText("Host")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Co-host")).toBeInTheDocument();
    expect(within(rows[2]).queryByText(/host/i)).not.toBeInTheDocument();
  });

  it("gives participants no room management actions", () => {
    render(<ParticipantList participants={PEOPLE} selfParticipantId="pt_tuan" selfRole="participant" permissions={permissionsFor("participant")} />);
    expect(screen.queryAllByRole("button", { name: /Actions for/ })).toHaveLength(0);
  });

  it("host: participant → Mute / Make co-host / Remove; co-host → Remove co-host", async () => {
    const onSetRole = vi.fn();
    const onRemove = vi.fn();
    render(
      <ParticipantList
        participants={PEOPLE}
        selfParticipantId="pt_huy"
        selfRole="host"
        permissions={permissionsFor("host")}
        onMuteParticipant={vi.fn()}
        onSetRole={onSetRole}
        onRemoveParticipant={onRemove}
      />,
    );
    expect(menuFor("Huy")).toBeNull(); // never on yourself
    await userEvent.click(menuFor("Tuan")!);
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Mute", "Make co-host", "Remove from meeting"]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Make co-host" }));
    expect(onSetRole).toHaveBeenCalledWith("pt_tuan", "co_host");

    await userEvent.click(menuFor("Kenji")!);
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Mute", "Remove co-host", "Remove from meeting"]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Remove from meeting" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onRemove).toHaveBeenCalledWith("pt_kenji");
  });

  it("co-host: only participants, and no role changes", async () => {
    render(
      <ParticipantList
        participants={PEOPLE}
        selfParticipantId="pt_kenji"
        selfRole="co_host"
        permissions={permissionsFor("co_host")}
        onMuteParticipant={vi.fn()}
        onSetRole={vi.fn()}
        onRemoveParticipant={vi.fn()}
      />,
    );
    expect(menuFor("Huy")).toBeNull(); // can't touch the host
    await userEvent.click(menuFor("Tuan")!);
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Mute", "Remove from meeting"]);
  });
});

describe("Room security", () => {
  const noop = () => undefined;

  it("is host-only; others only see that the room is locked", () => {
    const { rerender } = render(
      <RoomSecurityPanel passwordRequired locked={false} permissions={permissionsFor("co_host")} pendingAction={null} onSetLocked={noop} onChangePassword={async () => undefined} onRemovePassword={noop} />,
    );
    expect(screen.queryByText("Room security")).not.toBeInTheDocument();
    rerender(
      <RoomSecurityPanel passwordRequired locked permissions={permissionsFor("participant")} pendingAction={null} onSetLocked={noop} onChangePassword={async () => undefined} onRemovePassword={noop} />,
    );
    expect(screen.getByText(/This meeting is locked by the host/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lets the host lock and change the password without ever showing it", async () => {
    const onSetLocked = vi.fn();
    const onChangePassword = vi.fn(async () => undefined);
    render(
      <RoomSecurityPanel passwordRequired locked={false} permissions={permissionsFor("host")} pendingAction={null} onSetLocked={onSetLocked} onChangePassword={onChangePassword} onRemovePassword={noop} />,
    );
    expect(screen.getByText("Password protected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Lock meeting" }));
    expect(onSetLocked).toHaveBeenCalledWith(true);

    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByLabelText("New password")).toHaveValue("");
    await userEvent.type(screen.getByLabelText("New password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(screen.getByText("Password must be at least 6 characters.")).toBeInTheDocument();
    expect(onChangePassword).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText("New password"));
    await userEvent.type(screen.getByLabelText("New password"), "new-secret-1");
    await userEvent.type(screen.getByLabelText("Confirm password"), "new-secret-1");
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(onChangePassword).toHaveBeenCalledWith("new-secret-1");
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });
});

describe("roles (render-only mirror of the server matrix)", () => {
  it("matches the server's permissions", () => {
    expect(Object.values(permissionsFor("host")).every(Boolean)).toBe(true);
    const coHost = permissionsFor("co_host");
    expect(coHost.can_manage_ai && coHost.can_manage_recording && coHost.can_remove_participant).toBe(true);
    expect(coHost.can_manage_password || coHost.can_assign_cohost || coHost.can_lock_room).toBe(false);
    expect(Object.values(permissionsFor("participant")).some(Boolean)).toBe(false);
    expect(outranks("co_host", "host")).toBe(false);
    expect(formatMeetingTitle("  ", ["vi", "ja"])).toMatch(/Vietnamese.*Japanese meeting/);
    expect(formatMeetingTitle("Weekly", ["vi"])).toBe("Weekly");
  });
});
