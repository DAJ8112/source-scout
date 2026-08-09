import type { components } from "./api.generated";

export interface Diagnostic {
  code?: string;
  message?: string;
  [key: string]: unknown;
}

export interface WorkdayFacet {
  facet_parameter: string;
  label: string;
  id: string;
}

export interface AvailableFacet {
  facet_parameter: string;
  label: string;
  values: Array<{ id: string; label: string; count?: number }>;
}

type GeneratedValidation = components["schemas"]["ValidationResult"];
export type ValidationResult = Omit<
  GeneratedValidation,
  "sample_jobs" | "available_facets" | "warnings" | "diagnostics"
> & {
  sample_jobs: Array<{ title?: string; url: string }>;
  available_facets: AvailableFacet[];
  warnings: Diagnostic[];
  diagnostics: Diagnostic;
};

type GeneratedSource = components["schemas"]["SourceRead"];
export type Source = Omit<
  GeneratedSource,
  "connector_config" | "detection" | "last_validation"
> & {
  connector_config: Record<string, unknown>;
  detection: Record<string, unknown>;
  last_validation: ValidationResult | Record<string, never>;
};

type GeneratedScan = components["schemas"]["ScanRead"];
export type Scan = Omit<GeneratedScan, "progress" | "warnings" | "error_diagnostics"> & {
  progress: Record<string, unknown>;
  warnings: Diagnostic[];
  error_diagnostics: Diagnostic;
};

export type Job = components["schemas"]["JobRead"];
export type JobsPage = components["schemas"]["JobsPage"];
export type CurrentJob = components["schemas"]["CurrentJobRead"];
export type CurrentJobsPage = components["schemas"]["CurrentJobsPage"];
export type ReferralContact = components["schemas"]["ReferralContactRead"];
