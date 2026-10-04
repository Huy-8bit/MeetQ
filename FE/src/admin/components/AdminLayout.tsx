import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Activity, AlertTriangle, BarChart3, Bot, History, LayoutDashboard, LogOut, Menu, Radio, Settings, X, type LucideIcon, Film } from "lucide-react";
import { useAdminApi, useAdminSession } from "../auth/AdminSession";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { HEALTH_LABELS } from "../lib/format";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

// Adding a section (e.g. a future Glossary under Configuration) is one entry here plus a route.
const NAV_GROUPS: Array<{ label: string | null; items: NavItem[] }> = [
  { label: null, items: [{ to: "/admin", label: "Overview", icon: LayoutDashboard, end: true }] },
  {
    label: "Operations",
    items: [
      { to: "/admin/live-rooms", label: "Live Rooms", icon: Radio },
      { to: "/admin/meetings", label: "Meetings", icon: History },
      { to: "/admin/recordings", label: "Recordings", icon: Film },
      { to: "/admin/ai-relay", label: "AI Relay", icon: Bot },
      { to: "/admin/issues", label: "Issues", icon: AlertTriangle },
    ],
  },
  { label: "Insights", items: [{ to: "/admin/analytics", label: "Analytics", icon: BarChart3 }] },
  { label: "Configuration", items: [{ to: "/admin/settings", label: "Settings", icon: Settings }] },
];

const HEALTH_POLL_MS = 30_000;

function SystemStatus() {
  const api = useAdminApi();
  const query = useAdminQuery("system-health", api.health, { intervalMs: HEALTH_POLL_MS });
  const status = query.data?.overall ?? (query.error ? "unknown" : null);
  const label = status ? HEALTH_LABELS[status] : "Checking…";
  const problems = query.data?.components.filter((component) => component.status !== "healthy") ?? [];
  const title = problems.length
    ? problems.map((component) => `${component.label}: ${component.detail ?? component.status}`).join("\n")
    : "All components healthy";
  return (
    <Link to="/admin" className={`adm-system-status is-${status ?? "unknown"}`} title={title}>
      <Activity size={14} aria-hidden="true" />
      <span>System</span>
      <strong>{query.error && !query.data ? "Unreachable" : label}</strong>
    </Link>
  );
}

export function AdminLayout() {
  const { logout, admin } = useAdminSession();
  const location = useLocation();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  return (
    <div className={["adm", navOpen ? "is-nav-open" : ""].filter(Boolean).join(" ")}>
      <a className="adm-skip" href="#adm-main">Skip to content</a>
      <header className="adm-topbar">
        <button
          type="button"
          className="adm-nav-toggle btn btn--ghost btn--icon"
          aria-label={navOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={navOpen}
          aria-controls="adm-sidebar"
          onClick={() => setNavOpen((value) => !value)}
        >
          {navOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <Link to="/admin" className="brand adm-brand">
          <span className="brand-mark" aria-hidden="true">MQ</span>
          MeetQ <span className="adm-brand-suffix">Admin</span>
        </Link>
        <div className="adm-topbar-end">
          <SystemStatus />
          {admin ? (
            <span className="adm-admin-name adm-hide-mobile" title={admin.username}>
              {admin.displayName}
            </span>
          ) : null}
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void logout().then(() => navigate("/admin/login", { replace: true }))}
          >
            <LogOut size={14} aria-hidden="true" />
            <span className="adm-hide-mobile">Sign out</span>
          </button>
        </div>
      </header>

      <nav className="adm-sidebar" id="adm-sidebar" aria-label="Admin">
        {NAV_GROUPS.map((group, index) => (
          <div className="adm-nav-group" key={group.label ?? index}>
            {group.label ? <p className="adm-nav-heading">{group.label}</p> : null}
            <ul>
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <li key={to}>
                  <NavLink to={to} end={end} className="adm-nav-link">
                    <Icon size={16} aria-hidden="true" />
                    {label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <p className="adm-sidebar-note">MeetQ does not record audio or video. Transcripts, relays, chat and summaries are the only meeting content stored.</p>
      </nav>
      {navOpen ? <button type="button" className="adm-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} /> : null}

      <main className="adm-main" id="adm-main" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
