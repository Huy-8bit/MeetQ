import { useEffect, useState } from "react";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { ApiError } from "../../lib/api";
import { useAdminApi } from "../auth/AdminSession";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { formatDateTime } from "../lib/format";
import { QueryBoundary, Section } from "./Page";

/** Settings → Data & Retention: system default for NEW meeting archives. */
export function RetentionSettingsSection() {
  const api = useAdminApi();
  const query = useAdminQuery("retention-settings", api.retentionSettings);
  const [days, setDays] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  useEffect(() => {
    if (query.data) setDays(String(query.data.default_retention_days));
  }, [query.data]);

  const parsed = Number(days);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 365;

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await api.updateRetentionSettings(parsed);
      setMessage({ tone: "success", text: "Saved. New meeting archives use this retention." });
      query.refetch();
    } catch (caught) {
      setMessage({ tone: "danger", text: caught instanceof ApiError ? caught.message : "Couldn't save." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      id="data-retention"
      title="Data & retention"
      description="Meeting recordings, transcripts, relay, chat and summaries are automatically deleted after this period."
    >
      <QueryBoundary query={query}>
        {(settings) => (
          <form
            className="adm-retention-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (valid) void save();
            }}
          >
            <label className="adm-retention-field">
              <span>Default retention (days)</span>
              <input
                className="input"
                type="number"
                min={1}
                max={365}
                step={1}
                value={days}
                onChange={(event) => setDays(event.target.value)}
              />
            </label>
            <p className="adm-muted">
              Applies to new meeting archives. Existing archives keep their expiry; change one from its archive page.
              {settings.updated_at ? ` Last changed ${formatDateTime(settings.updated_at)} by ${settings.updated_by}.` : " Currently the configured default."}
            </p>
            <div className="adm-retention-actions">
              <Button type="submit" variant="primary" size="sm" disabled={!valid || saving || parsed === settings.default_retention_days} loading={saving}>
                Save changes
              </Button>
            </div>
            {message ? <Alert tone={message.tone}>{message.text}</Alert> : null}
          </form>
        )}
      </QueryBoundary>
    </Section>
  );
}
