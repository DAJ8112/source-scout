import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type {
  FeedPage,
  Job,
  JobUserStatePatch,
  Scan,
  SearchProfile,
  SearchProfilePatch,
  Source,
  ValidationResult,
  WorkdayFacet,
} from "./api.types";
import "./styles.css";

const TERMINAL = new Set(["success", "success_with_warnings", "failed", "interrupted"]);

function messageOf(value: unknown): string {
  if (value instanceof Error) return value.message;
  return "Unexpected error";
}

function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

function ProfilePanel({
  profile,
  busy,
  onSave,
  onUpload,
  onRematch,
}: {
  profile: SearchProfile;
  busy: boolean;
  onSave: (payload: SearchProfilePatch) => Promise<void>;
  onUpload: (file: File) => Promise<void>;
  onRematch: () => Promise<void>;
}) {
  const [targetRoles, setTargetRoles] = useState("");
  const [adjacentRoles, setAdjacentRoles] = useState("");
  const [locations, setLocations] = useState("");
  const [employmentTypes, setEmploymentTypes] = useState("");
  const [requiredTerms, setRequiredTerms] = useState("");
  const [excludedTerms, setExcludedTerms] = useState("");
  const [remotePreference, setRemotePreference] = useState(profile.remote_preference);
  const [preferenceNotes, setPreferenceNotes] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [resumeFile, setResumeFile] = useState<File | null>(null);

  useEffect(() => {
    setTargetRoles(profile.target_roles.join(", "));
    setAdjacentRoles(profile.adjacent_roles.join(", "));
    setLocations(profile.preferred_locations.join(", "));
    setEmploymentTypes(profile.employment_types.join(", "));
    setRequiredTerms(profile.required_terms.join(", "));
    setExcludedTerms(profile.excluded_terms.join(", "));
    setRemotePreference(profile.remote_preference);
    setPreferenceNotes(profile.preference_notes);
    setResumeText(profile.resume_text);
  }, [profile]);

  async function save(event: FormEvent) {
    event.preventDefault();
    await onSave({
      resume_text: resumeText,
      target_roles: splitList(targetRoles),
      adjacent_roles: splitList(adjacentRoles),
      preferred_locations: splitList(locations),
      remote_preference: remotePreference as SearchProfilePatch["remote_preference"],
      employment_types: splitList(employmentTypes),
      required_terms: splitList(requiredTerms),
      excluded_terms: splitList(excludedTerms),
      preference_notes: preferenceNotes,
    });
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!resumeFile) return;
    await onUpload(resumeFile);
    setResumeFile(null);
  }

  const ready = Boolean(resumeText.trim() && splitList(targetRoles).length);
  return (
    <section className="profile-panel">
      <div className="section-heading">
        <div><p className="eyebrow">Matching profile</p><h2>Tell the monitor what fits</h2></div>
        <span>Version {profile.version}</span>
      </div>
      <form className="resume-upload" onSubmit={upload}>
        <label>Resume PDF<input type="file" accept="application/pdf,.pdf" onChange={(event) => setResumeFile(event.target.files?.[0] ?? null)} /></label>
        <button className="secondary" type="submit" disabled={!resumeFile || busy}>Extract text</button>
        <small>{profile.resume_filename ? `Extracted from ${profile.resume_filename}` : "The PDF is discarded after extraction."}</small>
      </form>
      <form className="profile-form" onSubmit={save}>
        <label>Target roles<input required value={targetRoles} onChange={(event) => setTargetRoles(event.target.value)} placeholder="Data Engineer, AI Engineer" /></label>
        <label>Adjacent roles<input value={adjacentRoles} onChange={(event) => setAdjacentRoles(event.target.value)} placeholder="Data Platform Engineer" /></label>
        <label>Preferred locations<input value={locations} onChange={(event) => setLocations(event.target.value)} placeholder="Remote, Indianapolis" /></label>
        <label>Work arrangement<select value={remotePreference} onChange={(event) => setRemotePreference(event.target.value)}><option value="no_preference">No preference</option><option value="remote_only">Remote only</option><option value="remote_or_hybrid">Remote or hybrid</option><option value="on_site_ok">On-site is okay</option></select></label>
        <label>Employment types<input value={employmentTypes} onChange={(event) => setEmploymentTypes(event.target.value)} placeholder="FULL_TIME" /></label>
        <label>Preferred terms<input value={requiredTerms} onChange={(event) => setRequiredTerms(event.target.value)} placeholder="Python, LLM, AWS" /></label>
        <label>Excluded terms<input value={excludedTerms} onChange={(event) => setExcludedTerms(event.target.value)} placeholder="Commission only" /></label>
        <label className="wide">Other preferences<textarea value={preferenceNotes} onChange={(event) => setPreferenceNotes(event.target.value)} placeholder="Prefer product teams and platform ownership." /></label>
        <label className="wide">Editable resume text<textarea className="resume-text" value={resumeText} onChange={(event) => setResumeText(event.target.value)} placeholder="Upload a PDF or paste resume text here." /></label>
        <div className="profile-actions wide">
          <button type="submit" disabled={busy}>Save profile</button>
          <button type="button" className="secondary" disabled={busy || !ready} onClick={onRematch}>Run matching</button>
          <small>Claude receives selected resume evidence and job text—not the PDF or referral contacts.</small>
        </div>
      </form>
    </section>
  );
}

function SourceCard({
  source,
  onChange,
  onScanComplete,
}: {
  source: Source;
  onChange: (source: Source) => void;
  onScanComplete: () => Promise<void>;
}) {
  const [validation, setValidation] = useState<ValidationResult | null>(
    "valid" in source.last_validation ? (source.last_validation as ValidationResult) : null,
  );
  const [scan, setScan] = useState<Scan | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactUrl, setContactUrl] = useState("");
  const [contactNotes, setContactNotes] = useState("");
  const selected = (source.connector_config.selected_facets as WorkdayFacet[] | undefined) ?? [];

  async function validate() {
    setError("");
    try {
      const result = await api.validateSource(source.id);
      setValidation(result.validation);
      onChange(result.source);
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  async function toggleFacet(facet: WorkdayFacet) {
    const included = selected.some((item) => item.id === facet.id);
    const selected_facets = included
      ? selected.filter((item) => item.id !== facet.id)
      : [...selected, facet];
    try {
      onChange(await api.patchSource(source.id, {
        connector_config: { ...source.connector_config, selected_facets },
      }));
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  async function beginScan() {
    setError("");
    setJobs([]);
    try {
      const created = await api.createScan(source.id);
      setScan(created);
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  async function toggleMonitoring() {
    setError("");
    try {
      onChange(await api.patchSource(source.id, {
        monitoring_status: source.monitoring_status === "active" ? "paused" : "active",
      }));
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  useEffect(() => {
    if (!scan || TERMINAL.has(scan.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await api.scan(scan.id);
        setScan(next);
        if (next.status === "success" || next.status === "success_with_warnings") {
          setJobs((await api.jobs(next.id)).items);
          await onScanComplete();
        }
      } catch (reason) {
        setError(messageOf(reason));
      }
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [onScanComplete, scan]);

  async function addContact(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const contact = await api.createContact(source.id, contactName, contactUrl, contactNotes);
      onChange({
        ...source,
        contacts: [...source.contacts, contact].sort((left, right) => left.name.localeCompare(right.name)),
      });
      setContactName("");
      setContactUrl("");
      setContactNotes("");
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  async function removeContact(contactId: string) {
    if (!window.confirm("Remove this referral contact?")) return;
    setError("");
    try {
      await api.deleteContact(source.id, contactId);
      onChange({ ...source, contacts: source.contacts.filter((contact) => contact.id !== contactId) });
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  const diagnostics = validation?.diagnostics;
  const available = validation?.available_facets ?? [];

  return (
    <article className="source-card">
      <div className="source-heading">
        <div>
          <h2>{source.company}</h2>
          <a href={source.url} target="_blank" rel="noreferrer">{new URL(source.url).hostname}</a>
        </div>
        <span className={`status status-${source.health_status}`}>{source.health_status.replaceAll("_", " ")}</span>
      </div>
      <dl className="metadata">
        <div><dt>Platform</dt><dd>{source.detected_platform ?? "Undetected"}</dd></div>
        <div><dt>Connector</dt><dd>{source.connector_type ?? "Setup required"}</dd></div>
        <div><dt>Setup</dt><dd>{source.setup_status.replaceAll("_", " ")}</dd></div>
        <div><dt>Monitoring</dt><dd>{source.monitoring_status}</dd></div>
        <div><dt>Last success</dt><dd>{formatTime(source.last_successful_scan_at)}</dd></div>
        <div><dt>Next scan</dt><dd>{source.monitoring_status === "paused" ? "Paused" : formatTime(source.next_scan_at)}</dd></div>
      </dl>

      {source.detected_platform === "workday" && selected.length > 0 && (
        <fieldset>
          <legend>Workday facets</legend>
          {selected.map((facet) => (
            <label key={facet.id} className="facet">
              <input type="checkbox" checked onChange={() => toggleFacet(facet)} />
              <span>{facet.label}</span><small>{facet.facet_parameter}</small>
            </label>
          ))}
          {available.flatMap((group) => group.values.map((value) => ({
            facet_parameter: group.facet_parameter, label: value.label, id: value.id,
          }))).filter((facet) => !selected.some((item) => item.id === facet.id)).slice(0, 8).map((facet) => (
            <label key={facet.id} className="facet muted">
              <input type="checkbox" checked={false} onChange={() => toggleFacet(facet)} />
              <span>{facet.label}</span><small>{facet.facet_parameter}</small>
            </label>
          ))}
        </fieldset>
      )}

      {validation && (
        <div className={validation.valid ? "notice success" : "notice warning"}>
          {validation.valid
            ? `Validated${validation.job_count == null ? "" : ` · ${validation.job_count} jobs available`}`
            : diagnostics?.message ?? "Setup required"}
        </div>
      )}
      {error && <div role="alert" className="notice error">{error}</div>}

      <div className="actions">
        <button className="secondary" onClick={validate}>Validate source</button>
        <button onClick={beginScan} disabled={scan != null && !TERMINAL.has(scan.status)}>Scan now</button>
        <button className="text-button" type="button" onClick={toggleMonitoring}>{source.monitoring_status === "active" ? "Pause monitoring" : "Resume monitoring"}</button>
      </div>

      {scan && (
        <section className="scan" aria-live="polite">
          <strong>Scan: {scan.status.replaceAll("_", " ")}</strong>
          <span>{scan.jobs_persisted} jobs · {scan.pages_visited} pages</span>
          {TERMINAL.has(scan.status) && !scan.error_code && (
            <small>
              {scan.jobs_created} created · {scan.jobs_updated} changed · {scan.jobs_missing} missing
            </small>
          )}
          {scan.error_code && <div role="alert" className="notice error">{scan.error_diagnostics.message ?? scan.error_code}</div>}
          {scan.warnings.length > 0 && <small>{scan.warnings.length} diagnostic warning(s)</small>}
        </section>
      )}

      {jobs.length > 0 && (
        <section>
          <h3>Normalized jobs</h3>
          <ul className="jobs">
            {jobs.map((job) => (
              <li key={job.id}>
                <a href={job.canonical_url} target="_blank" rel="noreferrer">{job.title}</a>
                <span>{job.locations.join(" · ") || "Location not supplied"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="contacts">
        <div className="section-heading">
          <h3>Referral contacts</h3><span>{source.contacts.length}</span>
        </div>
        {source.contacts.length === 0 ? <p className="empty">No referral contacts yet.</p> : (
          <ul className="contact-list">
            {source.contacts.map((contact) => (
              <li key={contact.id}>
                <div>
                  {contact.contact_url ? (
                    <a href={contact.contact_url} target="_blank" rel="noreferrer">{contact.name}</a>
                  ) : <strong>{contact.name}</strong>}
                  {contact.notes && <span>{contact.notes}</span>}
                </div>
                <button className="text-button" type="button" onClick={() => removeContact(contact.id)}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        <form className="contact-form" onSubmit={addContact}>
          <label>Name<input required value={contactName} onChange={(event) => setContactName(event.target.value)} placeholder="Taylor" /></label>
          <label>Contact link<input type="url" value={contactUrl} onChange={(event) => setContactUrl(event.target.value)} placeholder="https://linkedin.com/in/…" /></label>
          <label>Notes<input value={contactNotes} onChange={(event) => setContactNotes(event.target.value)} placeholder="Former teammate" /></label>
          <button type="submit" className="secondary">Add contact</button>
        </form>
      </section>
    </article>
  );
}

function MatchFeed({
  feed,
  loading,
  actionBusy,
  showDismissed,
  onToggleDismissed,
  onUpdateState,
}: {
  feed: FeedPage | null;
  loading: boolean;
  actionBusy: string | null;
  showDismissed: boolean;
  onToggleDismissed: () => void;
  onUpdateState: (jobId: string, payload: JobUserStatePatch) => Promise<void>;
}) {
  const [showIrrelevant, setShowIrrelevant] = useState(false);
  const visibleItems = (feed?.items ?? []).filter(
    (item) => showIrrelevant || item.match?.classification !== "irrelevant",
  );
  const counts = (feed?.items ?? []).reduce<Record<string, number>>((current, item) => {
    const classification = item.match?.classification ?? "unmatched";
    current[classification] = (current[classification] ?? 0) + 1;
    return current;
  }, {});
  return (
    <section className="inventory">
      <div className="section-heading">
        <div><p className="eyebrow">Opportunity feed</p><h2>Active matches</h2></div>
        <span>{feed?.total ?? 0} shown</span>
      </div>
      {feed && (
        <div className="feed-summary">
          <span><strong>{feed.unseen_strong}</strong> unseen strong</span>
          <span><strong>{feed.unseen_possible}</strong> unseen possible</span>
          <span><strong>{counts.unmatched ?? 0}</strong> unmatched</span>
          <span className={feed.provider_configured ? "provider-ready" : "provider-fallback"}>
            {feed.provider_configured ? "Claude configured" : "Local fallback · add ANTHROPIC_API_KEY"}
          </span>
          {(counts.irrelevant ?? 0) > 0 && <button className="text-button" type="button" onClick={() => setShowIrrelevant((value) => !value)}>{showIrrelevant ? "Hide irrelevant" : `Show ${counts.irrelevant} irrelevant`}</button>}
          {(feed.dismissed_total > 0 || showDismissed) && <button className="text-button" type="button" onClick={onToggleDismissed}>{showDismissed ? "Hide dismissed" : `Show ${feed.dismissed_total} dismissed`}</button>}
        </div>
      )}
      {loading ? <p>Loading matches…</p> : !feed || feed.items.length === 0 ? (
        <p className="empty">No durable jobs yet. Run a successful source scan to populate the feed.</p>
      ) : (
        <div className="job-grid">
          {visibleItems.map((item) => {
            const { job, match } = item;
            const classification = match?.classification ?? "unmatched";
            const seen = Boolean(item.state?.seen_at);
            const dismissed = Boolean(item.state?.dismissed_at);
            return (
              <article className={`job-card${dismissed ? " job-dismissed" : ""}`} key={job.id}>
                <div className="job-labels">
                  <span className={`match-class match-${classification}`}>{classification}</span>
                  <span>{item.company}{dismissed ? " · Dismissed" : seen ? " · Viewed" : ""}</span>
                </div>
                <h3><a href={job.canonical_url} target="_blank" rel="noreferrer">{job.title}</a></h3>
                <p>{job.locations.join(" · ") || "Location not supplied"}</p>
                <div className="job-meta">
                  <span>{job.initial_import ? "Existing at setup" : "New discovery"}</span>
                  {match && <span>{match.score}/100 · {match.provider === "anthropic" ? "Claude" : "Local fallback"}</span>}
                </div>
                <div className="job-actions">
                  {!seen && !dismissed && <button className="secondary" type="button" disabled={actionBusy === job.id} onClick={() => onUpdateState(job.id, { seen: true })}>Mark viewed</button>}
                  {dismissed ? (
                    <button className="secondary" type="button" disabled={actionBusy === job.id} onClick={() => onUpdateState(job.id, { dismissed: false })}>Restore</button>
                  ) : (
                    <button className="text-button" type="button" disabled={actionBusy === job.id} onClick={() => onUpdateState(job.id, { dismissed: true })}>Dismiss</button>
                  )}
                </div>
                {match && match.evidence.length > 0 && <ul className="match-reasons">{match.evidence.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>}
                {match && match.gaps.length > 0 && <details><summary>Important gaps</summary><ul className="match-gaps">{match.gaps.slice(0, 3).map((gap) => <li key={gap}>{gap}</li>)}</ul></details>}
                {item.contacts.length > 0 && (
                  <div className="job-contacts">
                    <strong>Referral contacts</strong>
                    {item.contacts.map((contact) => contact.contact_url ? (
                      <a key={contact.id} href={contact.contact_url} target="_blank" rel="noreferrer">{contact.name}</a>
                    ) : <span key={contact.id}>{contact.name}</span>)}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [company, setCompany] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<SearchProfile | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const [feed, setFeed] = useState<FeedPage | null>(null);
  const [feedLoading, setFeedLoading] = useState(true);
  const [showDismissed, setShowDismissed] = useState(false);
  const [jobActionBusy, setJobActionBusy] = useState<string | null>(null);

  const reloadFeed = useCallback(async (includeDismissed = showDismissed) => {
    try {
      setFeed(await api.feed(includeDismissed));
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setFeedLoading(false);
    }
  }, [showDismissed]);

  useEffect(() => {
    api.sources().then(setSources).catch((reason) => setError(messageOf(reason))).finally(() => setLoading(false));
    api.profile().then(setProfile).catch((reason) => setError(messageOf(reason)));
  }, []);

  useEffect(() => {
    setFeedLoading(true);
    void reloadFeed(showDismissed);
  }, [reloadFeed, showDismissed]);

  async function rematch() {
    setProfileBusy(true);
    setError("");
    try {
      await api.rematch();
      await reloadFeed();
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setProfileBusy(false);
    }
  }

  async function saveProfile(payload: SearchProfilePatch) {
    setProfileBusy(true);
    setError("");
    try {
      const next = await api.patchProfile(payload);
      setProfile(next);
      if (next.resume_text.trim() && next.target_roles.length > 0) {
        await api.rematch();
        await reloadFeed();
      }
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setProfileBusy(false);
    }
  }

  async function uploadResume(file: File) {
    setProfileBusy(true);
    setError("");
    try {
      const next = await api.uploadResume(file);
      setProfile(next);
      if (next.target_roles.length > 0) {
        await api.rematch();
        await reloadFeed();
      }
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setProfileBusy(false);
    }
  }

  async function updateJobState(jobId: string, payload: JobUserStatePatch) {
    setJobActionBusy(jobId);
    setError("");
    try {
      await api.patchJobState(jobId, payload);
      await reloadFeed(showDismissed);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setJobActionBusy(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const source = await api.createSource(company, url);
      setSources((current) => [...current, source]);
      setCompany("");
      setUrl("");
    } catch (reason) {
      setError(messageOf(reason));
    }
  }

  function replaceSource(next: Source) {
    setSources((current) => current.map((source) => source.id === next.id ? next : source));
  }

  return (
    <main>
      <header className="hero">
        <p className="eyebrow">Referral monitor · Core MVP</p>
        <h1>Jobs worth a referral, monitored at the source.</h1>
        <p>Track official careers pages, see what changed, and keep referral contacts beside every opportunity.</p>
      </header>

      {error && <div role="alert" className="notice error global-error">{error}</div>}

      {profile ? (
        <ProfilePanel
          profile={profile}
          busy={profileBusy}
          onSave={saveProfile}
          onUpload={uploadResume}
          onRematch={rematch}
        />
      ) : <section className="profile-panel"><p>Loading matching profile…</p></section>}

      <section className="onboarding">
        <div><p className="eyebrow">Add a source</p><h2>Connect an official careers page</h2></div>
        <form onSubmit={submit}>
          <label>Company<input required value={company} onChange={(event) => setCompany(event.target.value)} placeholder="CVS Health" /></label>
          <label>Official careers URL<input required type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://…" /></label>
          <button type="submit">Add source</button>
        </form>
      </section>

      <MatchFeed
        feed={feed}
        loading={feedLoading}
        actionBusy={jobActionBusy}
        showDismissed={showDismissed}
        onToggleDismissed={() => setShowDismissed((value) => !value)}
        onUpdateState={updateJobState}
      />

      <section className="source-list">
        <div className="section-heading"><h2>Sources</h2><span>{sources.length} configured</span></div>
        {loading ? <p>Loading sources…</p> : sources.length === 0 ? <p className="empty">No sources yet. Add one above to begin.</p> :
          sources.map((source) => <SourceCard key={source.id} source={source} onChange={replaceSource} onScanComplete={reloadFeed} />)}
      </section>
    </main>
  );
}
