import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { CurrentJob, Job, Scan, Source, ValidationResult, WorkdayFacet } from "./api.types";
import "./styles.css";

const TERMINAL = new Set(["success", "success_with_warnings", "failed", "interrupted"]);

function messageOf(value: unknown): string {
  if (value instanceof Error) return value.message;
  return "Unexpected error";
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
      onChange(await api.patchSource(source.id, { ...source.connector_config, selected_facets }));
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
    }, 100);
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

function JobInventory({ jobs, sources, loading }: { jobs: CurrentJob[]; sources: Source[]; loading: boolean }) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  return (
    <section className="inventory">
      <div className="section-heading">
        <div><p className="eyebrow">Durable inventory</p><h2>Active jobs</h2></div>
        <span>{jobs.length} open</span>
      </div>
      {loading ? <p>Loading active jobs…</p> : jobs.length === 0 ? (
        <p className="empty">No durable jobs yet. Run a successful source scan to populate the inventory.</p>
      ) : (
        <div className="job-grid">
          {jobs.map((job) => {
            const source = sourceById.get(job.source_id);
            return (
              <article className="job-card" key={job.id}>
                <div className="job-labels">
                  <span className="status status-healthy">{job.initial_import ? "Existing at setup" : "New"}</span>
                  <span>{source?.company ?? "Unknown company"}</span>
                </div>
                <h3><a href={job.canonical_url} target="_blank" rel="noreferrer">{job.title}</a></h3>
                <p>{job.locations.join(" · ") || "Location not supplied"}</p>
                {source && source.contacts.length > 0 && (
                  <div className="job-contacts">
                    <strong>Referral contacts</strong>
                    {source.contacts.map((contact) => contact.contact_url ? (
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
  const [currentJobs, setCurrentJobs] = useState<CurrentJob[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);

  const reloadCurrentJobs = useCallback(async () => {
    try {
      setCurrentJobs((await api.currentJobs()).items);
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setJobsLoading(false);
    }
  }, []);

  useEffect(() => {
    api.sources().then(setSources).catch((reason) => setError(messageOf(reason))).finally(() => setLoading(false));
    void reloadCurrentJobs();
  }, [reloadCurrentJobs]);

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

      <section className="onboarding">
        <div><p className="eyebrow">Add a source</p><h2>Connect an official careers page</h2></div>
        <form onSubmit={submit}>
          <label>Company<input required value={company} onChange={(event) => setCompany(event.target.value)} placeholder="CVS Health" /></label>
          <label>Official careers URL<input required type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://…" /></label>
          <button type="submit">Add source</button>
        </form>
        {error && <div role="alert" className="notice error">{error}</div>}
      </section>

      <JobInventory jobs={currentJobs} sources={sources} loading={jobsLoading} />

      <section className="source-list">
        <div className="section-heading"><h2>Sources</h2><span>{sources.length} configured</span></div>
        {loading ? <p>Loading sources…</p> : sources.length === 0 ? <p className="empty">No sources yet. Add one above to begin.</p> :
          sources.map((source) => <SourceCard key={source.id} source={source} onChange={replaceSource} onScanComplete={reloadCurrentJobs} />)}
      </section>
    </main>
  );
}
