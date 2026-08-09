import type {
  CurrentJobsPage,
  JobsPage,
  ReferralContact,
  Scan,
  Source,
  ValidationResult,
} from "./api.types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // Keep the HTTP fallback.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  sources: () => request<Source[]>("/api/sources"),
  createSource: (company: string, url: string) =>
    request<Source>("/api/sources", { method: "POST", body: JSON.stringify({ company, url }) }),
  patchSource: (id: string, connector_config: Record<string, unknown>) =>
    request<Source>(`/api/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ connector_config }),
    }),
  validateSource: (id: string) =>
    request<{ source: Source; validation: ValidationResult }>(`/api/sources/${id}/validate`, {
      method: "POST",
    }),
  createScan: (id: string) =>
    request<Scan>(`/api/sources/${id}/scans`, {
      method: "POST",
      body: JSON.stringify({ trigger: "manual" }),
    }),
  scan: (id: string) => request<Scan>(`/api/scans/${id}`),
  jobs: (id: string, page = 1) => request<JobsPage>(`/api/scans/${id}/jobs?page=${page}&page_size=25`),
  currentJobs: () => request<CurrentJobsPage>("/api/jobs?lifecycle_status=active&page_size=100"),
  createContact: (sourceId: string, name: string, contact_url: string, notes: string) =>
    request<ReferralContact>(`/api/sources/${sourceId}/contacts`, {
      method: "POST",
      body: JSON.stringify({
        name,
        contact_url: contact_url || null,
        notes: notes || null,
      }),
    }),
  deleteContact: (sourceId: string, contactId: string) =>
    request<void>(`/api/sources/${sourceId}/contacts/${contactId}`, { method: "DELETE" }),
};
