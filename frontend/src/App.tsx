import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import type { Job, Scan, Source, ValidationResult, WorkdayFacet } from "./api.types";
import "./styles.css";

const TERMINAL = new Set(["success", "success_with_warnings", "failed", "interrupted"]);

function messageOf(value: unknown): string {
  if (value instanceof Error) return value.message;
  return "Unexpected error";
}

function SourceCard({ source, onChange }: { source: Source; onChange: (source: Source) => void }) {
  const [validation, setValidation] = useState<ValidationResult | null>(
    "valid" in source.last_validation ? (source.last_validation as ValidationResult) : null,
  );
  const [scan, setScan] = useState<Scan | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
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
        }
      } catch (reason) {
        setError(messageOf(reason));
      }
    }, 100);
    return () => window.clearTimeout(timer);
  }, [scan]);

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
    </article>
  );
}

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [company, setCompany] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.sources().then(setSources).catch((reason) => setError(messageOf(reason))).finally(() => setLoading(false));
  }, []);

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
        <p className="eyebrow">Connector lab · Milestone 1</p>
        <h1>Official careers, one observable scan at a time.</h1>
        <p>Add a source, verify how it is read, then inspect the exact normalized observations persisted for a scan.</p>
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

      <section className="source-list">
        <div className="section-heading"><h2>Sources</h2><span>{sources.length} configured</span></div>
        {loading ? <p>Loading sources…</p> : sources.length === 0 ? <p className="empty">No sources yet. Add one above to begin.</p> :
          sources.map((source) => <SourceCard key={source.id} source={source} onChange={replaceSource} />)}
      </section>
    </main>
  );
}
