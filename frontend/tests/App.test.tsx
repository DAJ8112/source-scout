import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../src/App";

const source = {
  id: "source-1", company: "CVS Health", url: "https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers",
  detected_platform: "workday", connector_type: "workday_cxs",
  connector_config: { selected_facets: [{ facet_parameter: "timeType", label: "Full time", id: "facet-1" }] },
  detection: {}, setup_status: "unvalidated", health_status: "unknown", last_validation_at: null,
  last_validation: {}, contacts: [], created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const emptyCurrentJobs = { items: [], page: 1, page_size: 100, total: 0 };

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

test("onboards and validates a source with facet selection", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(() => response([]))
    .mockImplementationOnce(() => response(emptyCurrentJobs))
    .mockImplementationOnce(() => response(source, 201))
    .mockImplementationOnce(() => response({ source: { ...source, health_status: "healthy", setup_status: "ready" }, validation: {
      valid: true, setup_status: "ready", job_count: 12, sample_jobs: [], warnings: [], diagnostics: {},
      available_facets: [{ facet_parameter: "timeType", label: "Time type", values: [{ id: "facet-2", label: "Part time" }] }],
    }}));
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Company"), "CVS Health");
  await user.type(screen.getByLabelText("Official careers URL"), source.url);
  await user.click(screen.getByRole("button", { name: "Add source" }));
  expect(await screen.findByText("CVS Health")).toBeInTheDocument();
  expect(screen.getByLabelText(/Full time/)).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Validate source" }));
  expect(await screen.findByText("Validated · 12 jobs available")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(4);
});

test("polls a scan, renders normalized results, and presents failures", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(() => response([source]))
    .mockImplementationOnce(() => response(emptyCurrentJobs))
    .mockImplementationOnce(() => response({ id: "scan-1", source_id: source.id, trigger: "manual", status: "queued", created_at: "", started_at: null, finished_at: null, progress: {}, jobs_found: 0, jobs_persisted: 0, jobs_created: 0, jobs_updated: 0, jobs_missing: 0, pages_visited: 0, warnings: [], error_code: null, error_diagnostics: {} }, 202))
    .mockImplementationOnce(() => response({ id: "scan-1", source_id: source.id, trigger: "manual", status: "success", created_at: "", started_at: "", finished_at: "", progress: {}, jobs_found: 1, jobs_persisted: 1, jobs_created: 1, jobs_updated: 0, jobs_missing: 0, pages_visited: 2, warnings: [], error_code: null, error_diagnostics: {} }))
    .mockImplementationOnce(() => response({ items: [{ id: "job-1", scan_run_id: "scan-1", source_id: source.id, external_id: "R1", canonical_url: "https://example.com/job/1", title: "Data Engineer", locations: ["Remote"], employment_type: "FULL_TIME", posted_date: null, description_html: null, description_text: null, content_fingerprint: "abc", raw_metadata: {}, observed_at: "" }], page: 1, page_size: 25, total: 1 }))
    .mockImplementationOnce(() => response({ items: [{ id: "current-1", source_id: source.id, external_id: "R1", canonical_url: "https://example.com/job/1", title: "Durable Data Engineer", locations: ["Remote"], employment_type: "FULL_TIME", posted_date: null, description_html: null, description_text: null, content_fingerprint: "abc", raw_metadata: {}, lifecycle_status: "active", consecutive_successful_absences: 0, initial_import: true, first_discovered_at: "", last_observed_at: "", created_at: "", updated_at: "" }], page: 1, page_size: 100, total: 1 }));
  render(<App />);
  const user = userEvent.setup();
  expect(await screen.findByText("CVS Health")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Scan now" }));
  expect(await screen.findByText("Data Engineer", {}, { timeout: 2000 })).toBeInTheDocument();
  expect(screen.getAllByText("Remote")).toHaveLength(2);
  expect(screen.getByText("1 created · 0 changed · 0 missing")).toBeInTheDocument();
  expect(await screen.findByText("Durable Data Engineer")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Scan: success")).toBeInTheDocument());
});

test("shows API errors during onboarding", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(() => response([]))
    .mockImplementationOnce(() => response(emptyCurrentJobs))
    .mockImplementationOnce(() => response({ detail: "This careers URL already exists" }, 409));
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Company"), "Duplicate");
  await user.type(screen.getByLabelText("Official careers URL"), "https://example.com/jobs");
  await user.click(screen.getByRole("button", { name: "Add source" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
});

test("adds a referral contact to a source", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockImplementationOnce(() => response([source]))
    .mockImplementationOnce(() => response(emptyCurrentJobs))
    .mockImplementationOnce(() => response({
      id: "contact-1", source_id: source.id, name: "Taylor",
      contact_url: "https://www.linkedin.com/in/taylor", notes: "Former teammate",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    }, 201));
  render(<App />);
  const user = userEvent.setup();
  expect(await screen.findByText("CVS Health")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Name"), "Taylor");
  await user.type(screen.getByLabelText("Contact link"), "https://www.linkedin.com/in/taylor");
  await user.type(screen.getByLabelText("Notes"), "Former teammate");
  await user.click(screen.getByRole("button", { name: "Add contact" }));
  expect(await screen.findByRole("link", { name: "Taylor" })).toBeInTheDocument();
  expect(screen.getByText("Former teammate")).toBeInTheDocument();
});
