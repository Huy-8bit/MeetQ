import { Badge } from "../../components/ui/Badge";
import { Alert } from "../../components/ui/Alert";
import type { ConfigItem } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { PageHeader, QueryBoundary, Section } from "../components/Page";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { RetentionSettingsSection } from "../components/RetentionSettingsSection";
import { formatDuration, formatNumber } from "../lib/format";

function formatValue(item: ConfigItem): string {
  if (item.value === null || item.value === undefined) return "No limit";
  if (typeof item.value === "boolean") return item.value ? "Enabled" : "Disabled";
  if (typeof item.value === "number") {
    if (item.unit === "seconds") return `${formatDuration(item.value)} (${formatNumber(item.value)} s)`;
    return `${formatNumber(item.value)}${item.unit && item.unit !== "seconds" ? ` ${item.unit}` : ""}`;
  }
  return String(item.value);
}

function ConfigTable({ items, caption }: { items: ConfigItem[]; caption: string }) {
  return (
    <div className="adm-table-scroll">
      <table className="adm-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Setting</th>
            <th scope="col">Value</th>
            <th scope="col" className="hide-narrow">Source</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.key}>
              <td>
                <span className="adm-cell-stack">
                  <span>{item.label}</span>
                  {item.note ? <span className="adm-code">{item.note}</span> : null}
                </span>
              </td>
              <td><strong>{formatValue(item)}</strong></td>
              <td className="hide-narrow"><Badge outline>{item.source}</Badge></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SettingsPage() {
  const api = useAdminApi();
  const query = useAdminQuery("admin-config", api.config);

  return (
    <>
      <PageHeader title="Settings" description="The configuration MeetQ is actually running with." />
      <QueryBoundary query={query}>
        {(config) => (
          <>
            {!config.editable ? (
              <Alert tone="info">
                Read-only. These values come from environment variables or code constants; change them in the deployment
                configuration (.env / docker-compose) and restart the services.
              </Alert>
            ) : null}
            <RetentionSettingsSection />
            <Section title="Rooms">
              <ConfigTable caption="Room configuration" items={config.room} />
            </Section>
            <Section title="AI">
              <ConfigTable caption="AI configuration" items={config.ai} />
            </Section>
            <Section title="Languages" description="Languages available when creating a room. The list is fixed in code.">
              <ul className="adm-chips">
                {config.languages.map((language) => (
                  <li key={language.code}>
                    <Badge tone={language.enabled ? "success" : "neutral"} dot>
                      {language.label} <span className="adm-code">{language.code}</span>
                    </Badge>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Notifications" description="Operator notifications are sent to Telegram.">
              <div className="adm-table-scroll">
                <table className="adm-table">
                  <caption className="sr-only">Notification events</caption>
                  <thead>
                    <tr>
                      <th scope="col">Event</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {config.notifications.map((item) => (
                      <tr key={item.event}>
                        <td>{item.label}</td>
                        <td>
                          {!item.supported ? (
                            <Badge outline>Not supported yet</Badge>
                          ) : item.enabled ? (
                            <Badge tone="success" dot>On · {item.channel}</Badge>
                          ) : (
                            <Badge dot>Off</Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
            <Section title="Operations">
              <ConfigTable caption="Operations configuration" items={config.operations} />
            </Section>
          </>
        )}
      </QueryBoundary>
    </>
  );
}
