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

const profile = {
  id: "profile-1", resume_text: "", resume_filename: null, target_roles: [], adjacent_roles: [],
  preferred_locations: [], remote_preference: "no_preference", employment_types: [], required_terms: [],
  excluded_terms: [], preference_notes: "", version: 1,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const emptyFeed = { items: [], total: 0, profile_ready: false, provider_configured: false };

const currentJob = {
  id: "current-1", source_id: source.id, external_id: "R1", canonical_url: "https://example.com/job/1",
  title: "Durable Data Engineer", locations: ["Remote"], employment_type: "FULL_TIME", posted_date: null,
  description_html: null, description_text: "Build Python pipelines.", content_fingerprint: "abc", raw_metadata: {},
  lifecycle_status: "active", consecutive_successful_absences: 0, initial_import: true,
  first_discovered_at: "2026-01-01T00:00:00Z", last_observed_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const match = {
  id: "match-1", job_id: currentJob.id, profile_id: profile.id, profile_version: 2,
  job_content_fingerprint: "abc", matcher_version: "hybrid-v1", classification: "strong", score: 88,
  role_score: 94, resume_score: 82, hard_constraint_pass: true, hard_constraint_reasons: [],
  evidence: ["Python and data-pipeline experience align"], gaps: ["Seniority is unclear"], provider: "local",
  provider_status: "fallback", model: null, prompt_version: "anthropic-job-match-v1", request_id: null,
  input_tokens: null, output_tokens: null, error: "ANTHROPIC_API_KEY is not configured",
  evaluated_at: "2026-01-01T00:00:00Z",
};

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

type Override = (url: string, method: string) => Promise<Response> | undefined;

function mockApi(override?: Override) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const custom = override?.(url, method);
    if (custom) return custom;
    if (url === "/api/sources" && method === "GET") return response([]);
    if (url === "/api/profile" && method === "GET") return response(profile);
    if (url === "/api/feed" && method === "GET") return response(emptyFeed);
    throw new Error(`Unexpected API call: ${method} ${url}`);
  });
}

test("onboards and validates a source with facet selection", async () => {
  mockApi((url, method) => {
    if (url === "/api/sources" && method === "POST") return response(source, 201);
    if (url === `/api/sources/${source.id}/validate` && method === "POST") return response({
      source: { ...source, health_status: "healthy", setup_status: "ready" }, validation: {
        valid: true, setup_status: "ready", job_count: 12, sample_jobs: [], warnings: [], diagnostics: {},
        available_facets: [{ facet_parameter: "timeType", label: "Time type", values: [{ id: "facet-2", label: "Part time" }] }],
      },
    });
  });
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Company"), "CVS Health");
  await user.type(screen.getByLabelText("Official careers URL"), source.url);
  await user.click(screen.getByRole("button", { name: "Add source" }));
  expect(await screen.findByText("CVS Health")).toBeInTheDocument();
  expect(screen.getByLabelText(/Full time/)).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Validate source" }));
  expect(await screen.findByText("Validated · 12 jobs available")).toBeInTheDocument();
});

test("polls a scan and refreshes the ranked feed", async () => {
  let feedCalls = 0;
  mockApi((url, method) => {
    if (url === "/api/sources" && method === "GET") return response([source]);
    if (url === "/api/feed" && method === "GET") {
      feedCalls += 1;
      return response(feedCalls === 1 ? emptyFeed : {
        items: [{ job: currentJob, company: source.company, contacts: [], match }],
        total: 1, profile_ready: true, provider_configured: false,
      });
    }
    if (url === `/api/sources/${source.id}/scans` && method === "POST") return response({
      id: "scan-1", source_id: source.id, trigger: "manual", status: "queued", created_at: "",
      started_at: null, finished_at: null, progress: {}, jobs_found: 0, jobs_persisted: 0,
      jobs_created: 0, jobs_updated: 0, jobs_missing: 0, pages_visited: 0, warnings: [],
      error_code: null, error_diagnostics: {},
    }, 202);
    if (url === "/api/scans/scan-1" && method === "GET") return response({
      id: "scan-1", source_id: source.id, trigger: "manual", status: "success", created_at: "",
      started_at: "", finished_at: "", progress: {}, jobs_found: 1, jobs_persisted: 1,
      jobs_created: 1, jobs_updated: 0, jobs_missing: 0, pages_visited: 2, warnings: [],
      error_code: null, error_diagnostics: {},
    });
    if (url.startsWith("/api/scans/scan-1/jobs") && method === "GET") return response({
      items: [{ id: "job-1", scan_run_id: "scan-1", source_id: source.id, external_id: "R1",
        canonical_url: "https://example.com/job/1", title: "Data Engineer", locations: ["Remote"],
        employment_type: "FULL_TIME", posted_date: null, description_html: null, description_text: null,
        content_fingerprint: "abc", raw_metadata: {}, observed_at: "" }],
      page: 1, page_size: 25, total: 1,
    });
  });
  render(<App />);
  const user = userEvent.setup();
  expect(await screen.findByText("CVS Health")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Scan now" }));
  expect(await screen.findByText("Data Engineer", {}, { timeout: 2000 })).toBeInTheDocument();
  expect(await screen.findByText("Durable Data Engineer")).toBeInTheDocument();
  expect(screen.getByText("88/100 · Local fallback")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Scan: success")).toBeInTheDocument());
});

test("saves a profile, runs matching, and renders explanations", async () => {
  const updatedProfile = { ...profile, resume_text: "Built Python pipelines.", target_roles: ["Data Engineer"], version: 2 };
  mockApi((url, method) => {
    if (url === "/api/profile" && method === "PATCH") return response(updatedProfile);
    if (url === "/api/profile/rematch" && method === "POST") return response({
      evaluated: 1, cached: 0, ai_succeeded: 0, local_fallbacks: 1, failed: 0,
    });
    if (url === "/api/feed" && method === "GET") return response({
      items: [{ job: currentJob, company: source.company, contacts: [], match }],
      total: 1, profile_ready: true, provider_configured: false,
    });
  });
  render(<App />);
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Target roles"), "Data Engineer");
  await user.type(screen.getByLabelText("Editable resume text"), "Built Python pipelines.");
  await user.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByText("Python and data-pipeline experience align")).toBeInTheDocument();
  expect(screen.getByText((_content, node) => node?.textContent === "1 strong")).toBeInTheDocument();
});

test("shows API errors during onboarding", async () => {
  mockApi((url, method) => {
    if (url === "/api/sources" && method === "POST") {
      return response({ detail: "This careers URL already exists" }, 409);
    }
  });
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Company"), "Duplicate");
  await user.type(screen.getByLabelText("Official careers URL"), "https://example.com/jobs");
  await user.click(screen.getByRole("button", { name: "Add source" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
});

test("adds a referral contact to a source", async () => {
  mockApi((url, method) => {
    if (url === "/api/sources" && method === "GET") return response([source]);
    if (url === `/api/sources/${source.id}/contacts` && method === "POST") return response({
      id: "contact-1", source_id: source.id, name: "Taylor",
      contact_url: "https://www.linkedin.com/in/taylor", notes: "Former teammate",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    }, 201);
  });
  render(<App />);
  const user = userEvent.setup();
  expect(await screen.findByText("CVS Health")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Name"), "Taylor");
  await user.type(screen.getByLabelText("Contact link"), "https://www.linkedin.com/in/taylor");
  await user.type(screen.getByLabelText("Notes"), "Former teammate");
  await user.click(screen.getByRole("button", { name: "Add contact" }));
  expect(await screen.findByRole("link", { name: "Taylor" })).toBeInTheDocument();
});
