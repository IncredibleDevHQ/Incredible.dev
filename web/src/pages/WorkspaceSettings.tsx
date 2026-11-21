import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "../components/ui/table";
import { useEffect, useState } from "react";
import { api, type AccountDetails, type ActivityLog, type Team } from "../api";
import { Skeleton } from "../components/Skeleton";
import { Dialog } from "radix-ui";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "../components/ui/dropdown-menu";
import {
  ChevronRight,
  EllipsisVertical,
  RefreshCw,
  UserPlus,
  X,
} from "lucide-react";
import { SearchChoice } from "../components/ui/ChoiceField";
import { InputField as TextField } from "../components/ui/InputField";
import { useHouse } from "../store";

export function LoginProfile() {
  const [saved, setSaved] = useState<AccountDetails | null>(null);
  const [draft, setDraft] = useState<AccountDetails>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    api
      .accountDetails()
      .then((data) => {
        if (active) {
          setSaved(data);
          setDraft(data);
        }
      })
      .catch(() => {
        if (active) setError("Couldn’t load account details.");
      });
    return () => {
      active = false;
    };
  }, [retry]);
  return (
    <section className="settings-form">
      <h2>Account details</h2>
      {error && <p role="alert">{error}</p>}
      {!saved ? (
        error ? (
          <button
            className="btn"
            onClick={() => {
              setError("");
              setRetry((n) => n + 1);
            }}
          >
            Try again
          </button>
        ) : (
          <Skeleton label="Loading account details" />
        )
      ) : (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              const result = await api.saveAccountDetails({
                ...draft,
                username: draft.username ?? "",
              });
              setSaved(result);
              setDraft(result);
              setMessage("Account details saved.");
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {(
            [
              ["first_name", "First name", "Your first name", "given-name"],
              ["last_name", "Last name", "Your last name", "family-name"],
              ["username", "Username", "e.g. alex_studio", "username"],
            ] as const
          ).map(([key, label, placeholder, autoComplete]) => (
            <TextField
              key={key}
              label={label}
              placeholder={placeholder}
              autoComplete={autoComplete}
              value={draft[key] ?? ""}
              disabled={busy}
              pattern={key === "username" ? "[a-zA-Z0-9_]{3,32}" : undefined}
              maxLength={key === "username" ? 32 : 80}
              hint={
                key === "username"
                  ? "Use 3–32 letters, numbers or underscores to sign in."
                  : undefined
              }
              onChange={(event) => {
                setDraft({ ...draft, [key]: event.target.value });
                setMessage("");
              }}
            />
          ))}
          <div>
            <button
              className="btn primary"
              disabled={busy || JSON.stringify(saved) === JSON.stringify(draft)}
            >
              Save account details
            </button>{" "}
            <span role="status">{message}</span>
          </div>
        </form>
      )}
    </section>
  );
}

export function Members() {
  const [team, setTeam] = useState<Team | null>(null);
  const [inviting, setInviting] = useState(false);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [manualLink, setManualLink] = useState("");
  const [confirm, setConfirm] = useState("");
  const [revision, refresh] = useState(0);
  useEffect(() => {
    let active = true;
    api
      .team()
      .then((data) => {
        if (active) setTeam(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [revision]);
  async function invite(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !email.trim()) return;
    setBusy(true);
    setFormError("");
    const address = email.trim().toLowerCase();
    try {
      const { id, invite_url, email_sent } = await api.invite(address);
      setTeam(
        (current) =>
          current && {
            ...current,
            members: [...current.members, { id, email: address, member: null, invite_url }],
          },
      );
      setInviting(false);
      setEmail("");
      setNotice(email_sent ? "Invitation emailed to " + address + "." : "Invitation saved, but the email could not be sent. Copy the invite link to share it.");
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function copyInvite(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setManualLink("");
      setNotice("Invite link copied.");
    } catch {
      setManualLink(link);
      setNotice("Select and copy the invite link below.");
    }
  }
  async function remove(id: string) {
    setManualLink("");
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.removeMember(id);
      setTeam(
        (current) =>
          current && {
            ...current,
            members: current.members.filter((row) => row.id !== id),
          },
      );
      setNotice("Project access updated.");
      setConfirm("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function enter(id: string) {
    setBusy(true);
    setError("");
    try {
      const { url } = await api.enterProject(id);
      window.location.assign(url + "/settings/organization");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <section className="settings-form roster">
      <header className="section-heading">
        <h2>Project access</h2>
        {team?.can_manage && (
          <Dialog.Root
            open={inviting}
            onOpenChange={(open) => {
              if (!busy) {
                setInviting(open);
                setFormError("");
                setNotice("");
              }
            }}
          >
            <Dialog.Trigger className="btn primary" disabled={busy}>
              <UserPlus size={15} /> Invite member
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="invite-overlay" />
              <Dialog.Content className="invite-dialog">
                <Dialog.Title>Invite member</Dialog.Title>
                <Dialog.Description>
                  We’ll email them a link to review and accept the invitation.
                </Dialog.Description>
                <form onSubmit={invite}>
                  <TextField
                    label="Invite by email"
                    placeholder="name@example.com"
                    type="email"
                    autoComplete="off"
                    required
                    value={email}
                    disabled={busy}
                    onChange={(event) => {
                      setEmail(event.target.value);
                      setFormError("");
                    }}
                  />
                  <div className="invite-role">
                    <span>Project role</span>
                    <strong>Member</strong>
                    <p>
                      Manage channels, work on episodes, and access project
                      files. Only the owner can invite people or revoke access.
                    </p>
                  </div>
                  {formError && <p role="alert">{formError}</p>}
                  <footer>
                    <Dialog.Close className="btn" type="button" disabled={busy}>
                      Cancel
                    </Dialog.Close>
                    <button
                      className="btn primary"
                      disabled={busy || !email.trim()}
                    >
                      {busy ? "Sending…" : "Send invitation"}
                    </button>
                  </footer>
                </form>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        )}
      </header>
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            className="btn"
            onClick={() => {
              setError("");
              refresh((n) => n + 1);
            }}
          >
            Retry
          </button>
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {manualLink && <TextField label="Invite link" readOnly value={manualLink} onFocus={event => event.target.select()} />}
      {!team ? (
        !error && <Skeleton label="Loading members" />
      ) : (
        <>
          <Table aria-label="Project members">
            <TableHeader>
              <TableRow>
                {[
                  "Member",
                  "Role",
                  "Status",
                  ...(team.can_manage ? ["Actions"] : []),
                ].map((h) => (
                  <TableHead key={h}>{h}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>{team.owner}</TableCell>
                <TableCell>Owner</TableCell>
                <TableCell>
                  <span className="member-status">Active</span>
                </TableCell>
                {team.can_manage && <TableCell />}
              </TableRow>
              {team.members.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.email}</TableCell>
                  <TableCell>Member</TableCell>
                  <TableCell>
                    <span
                      className={
                        "member-status " + (row.member ? "" : "pending")
                      }
                    >
                      {row.member ? "Active" : "Pending"}
                    </span>
                  </TableCell>
                  {team.can_manage && (
                    <TableCell>
                      {confirm === row.id ? (
                        <div className="row-actions">
                          <button
                            className="btn danger"
                            disabled={busy}
                            onClick={() => void remove(row.id)}
                          >
                            Confirm removal
                          </button>
                          <button
                            className="btn"
                            disabled={busy}
                            onClick={() => setConfirm("")}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="btn member-actions"
                              disabled={busy}
                              aria-label={"Actions for " + row.email}
                            >
                              <EllipsisVertical size={16} />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {!row.member && row.invite_url && <DropdownMenuItem
                              onSelect={() => void copyInvite(row.invite_url!)}>Copy invite link</DropdownMenuItem>}
                            <DropdownMenuItem
                              onSelect={() => {
                                setConfirm(row.id);
                                setNotice("");
                              }}
                            >
                              {row.member ? "Remove access" : "Revoke invite"}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {team.incoming.some((row) => row.owner !== team.project) && (
            <h2>Invitations and shared projects</h2>
          )}
          {team.incoming
            .filter((row) => row.owner !== team.project)
            .map((row) => (
              <div key={row.id} className="setting-row">
                <span>{row.email}’s project</span>
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => void enter(row.id)}
                >
                  {row.member ? "Open project" : "Accept invitation"}
                </button>
              </div>
            ))}
          {!team.can_manage && (
            <a href={team.personal_url + "/settings/organization"}>
              Return to my project
            </a>
          )}
        </>
      )}
    </section>
  );
}

const activityNames: Record<string, string> = {
  "POST /api/team/invite": "Created an invitation",
  "POST /api/team/{invite_id}/accept": "Accepted an invitation",
  "DELETE /api/team/{invite_id}": "Revoked project access",
  "PUT /api/account/details": "Updated account details",
  "PUT /api/profile": "Updated display name",
  "POST /api/profile/avatar": "Updated profile photo",
  "PUT /api/organization": "Updated organization",
  "POST /api/auth/login": "Signed in",
  "POST /api/auth/logout": "Signed out",
};
export function Logs() {
  const [selected, setSelected] = useState<
    ActivityLog["events"][number] | null
  >(null);
  const [actor, setActor] = useState("");
  const [cursors, setCursors] = useState<number[]>([]);
  const before = cursors.at(-1);
  const [loading, setLoading] = useState(true);
  const [log, setLog] = useState<ActivityLog | null>(null);
  const [error, setError] = useState("");
  const [revision, refresh] = useState(0);
  const people = useHouse((s) => s.people);
  useEffect(() => {
    let active = true;
    setError("");
    setLoading(true);
    api
      .activity(actor, before)
      .then((data) => {
        if (active) {
          setLog(data);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (active) {
          setLoading(false);
          setError(e.message);
        }
      });
    return () => {
      active = false;
    };
  }, [actor, before, revision]);
  return (
    <section className="settings-form">
      <header className="usage-heading">
        <h2>Project activity</h2>
        <div className="activity-tools" role="group" aria-label="Activity controls">
        {log && <div className="logs-filter">
            <SearchChoice
              label="Performed by"
              value={actor}
              options={[
                { value: "", label: "Everyone" },
                ...log.actors.map(({ actor, email }) => ({
                  value: actor,
                  label: people[actor]?.name ?? email,
                })),
              ]}
              onChange={(id) => {
                setActor(id);
                setCursors([]);
              }}
            />
          </div>}
        <button
          className="btn log-refresh"
          type="button"
          disabled={loading}
          aria-label="Refresh activity"
          title="Refresh activity"
          onClick={() => {
            setCursors([]);
            refresh((n) => n + 1);
          }}
        >
          <RefreshCw
            size={14}
            aria-hidden="true"
            className={loading ? "spin-icon" : undefined}
          />{" "}
          Refresh
        </button>
        </div>
      </header>
      {error && <p role="alert">{error}</p>}
      {log ? (
        <>
          {loading ? (
            <Skeleton label="Loading activity logs" />
          ) : error ? null : log.events.length ? (
            <div className="usage-table">
              <Table>
                <TableHeader>
                  <TableRow>
                    {["Time", "Performed by", "Action", "Status"].map((h) => (
                      <TableHead key={h}>{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {log.events.map((row) => (
                    <TableRow
                      key={row.id}
                      className="activity-row"
                      onClick={() => setSelected(row)}
                    >
                      <TableCell>
                        {new Date(row.happened * 1000).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        {people[row.actor]?.name ?? row.actor_email}
                      </TableCell>
                      <TableCell title={row.action}>
                        <button
                          id={"event-" + row.id}
                          type="button"
                          className="event-link"
                          aria-haspopup="dialog"
                        >
                          {activityNames[row.action] ?? row.action}
                        </button>
                      </TableCell>
                      <TableCell title={String(row.status)}>
                        <span
                          className={
                            "audit-status " +
                            (row.status >= 400 ? "failed" : "")
                          }
                        >
                          {row.status < 400 ? "Succeeded" : "Failed"}
                        </span>
                        <ChevronRight
                          className="row-chevron"
                          size={14}
                          aria-hidden="true"
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="muted">No recorded actions for this filter.</p>
          )}
          {cursors.length > 0 && (
            <button
              className="btn"
              disabled={loading}
              onClick={() => setCursors((prev) => prev.slice(0, -1))}
            >
              Newer actions
            </button>
          )}
          {log.more && (
            <button
              className="btn"
              disabled={loading}
              onClick={() =>
                setCursors((prev) => [...prev, log.events.at(-1)!.happened])
              }
            >
              Older actions
            </button>
          )}
        </>
      ) : (
        !error && <Skeleton label="Loading activity logs" />
      )}
      <Dialog.Root
        open={!!selected}
        onOpenChange={(open) => {
          if (!open && selected) {
            const id = selected.id;
            setSelected(null);
            requestAnimationFrame(() =>
              document.getElementById("event-" + id)?.focus(),
            );
          }
        }}
      >
        {selected && (
          <Dialog.Portal>
            <Dialog.Overlay className="invite-overlay" />
            <Dialog.Content
              className="event-sheet"
              onCloseAutoFocus={(event) => {
                event.preventDefault();
              }}
            >
              <header>
                <Dialog.Title>Event details</Dialog.Title>
                <Dialog.Close className="btn" aria-label="Close details">
                  <X size={16} />
                </Dialog.Close>
              </header>
              <Dialog.Description>
                {activityNames[selected.action] ?? selected.action}
              </Dialog.Description>
              <dl>
                {[
                  ["Result", selected.status < 400 ? "Succeeded" : "Failed"],
                  ["HTTP status", String(selected.status)],
                  [
                    "Time (UTC)",
                    new Date(selected.happened * 1000)
                      .toISOString()
                      .replace("T", " ")
                      .replace("Z", ""),
                  ],
                  ["Performed by", selected.actor_email],
                  ["Account ID", selected.actor],
                  ["Project member", selected.member_email],
                  ["Recorded action", selected.action],
                  [
                    "Response time",
                    selected.duration_ms == null
                      ? null
                      : selected.duration_ms + " ms",
                  ],
                  ["Event ID", selected.id],
                ].map(
                  ([label, value]) =>
                    value && (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value}</dd>
                      </div>
                    ),
                )}
              </dl>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </Dialog.Root>
    </section>
  );
}
