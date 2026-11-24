// Types mirroring the backend's OpenAPI schemas (docs/openapi.json). Field names match the API.

export type UserRole = "Reporter" | "Developer" | "ProjectManager" | "Administrator";
export type ProjectRole = "Reporter" | "Developer" | "ProjectManager";
export type Severity = "Low" | "Medium" | "High" | "Critical" | "Unclassified";
export type BugStatus = "Open" | "InProgress" | "Resolved" | "Verified" | "Closed";
export type AiStatus = "ok" | "degraded";
export type StepStatus = "ok" | "degraded" | "skipped";

export const BUG_STATUSES: readonly BugStatus[] = [
  "Open",
  "InProgress",
  "Resolved",
  "Verified",
  "Closed",
];
export const SEVERITIES: readonly Severity[] = [
  "Critical",
  "High",
  "Medium",
  "Low",
  "Unclassified",
];

export interface UserSummary {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
}

export interface UserMe extends UserSummary {
  is_active: boolean;
  created_at: string;
  email_notifications: boolean;
  push_notifications: boolean;
  ntfy_topic: string;
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
  expires_in: number;
  user: UserMe;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  my_role?: ProjectRole | null;
}

export interface Member {
  user: UserSummary;
  role: ProjectRole;
  joined_at: string;
}

export interface BugListItem {
  id: number;
  project_id: number;
  title: string;
  status: BugStatus;
  severity: Severity;
  ai_status: AiStatus;
  assignee: UserSummary | null;
  reporter: UserSummary | null;
  components: string[];
  created_at: string;
  updated_at: string;
}

export interface DuplicateMatch {
  bug_id: number;
  title: string;
  status: BugStatus;
  score: number;
}

export interface DeveloperSuggestion {
  developer_id: number;
  name: string;
  score: number;
  reason: string;
  alpha: number;
  history_score: number;
  profile_score: number;
  explored: boolean;
  notes: string[];
}

export interface StepInfo {
  status: StepStatus;
  elapsed_ms: number;
  detail: string | null;
}

export interface AiDetails {
  steps?: Record<string, StepInfo>;
  total_ms?: number;
  is_likely_duplicate?: boolean;
  notice?: string | null;
}

export interface Bug extends BugListItem {
  description: string;
  steps_to_reproduce: string;
  environment: string;
  close_reason: "fixed" | "invalid" | "duplicate" | null;
  duplicate_of_id: number | null;
  predicted_severity: Severity | null;
  severity_confidence: number | null;
  severity_overridden: boolean;
  duplicate_candidates: DuplicateMatch[];
  recommended_developers: DeveloperSuggestion[];
  ai_details: AiDetails;
  resolved_at: string | null;
  closed_at: string | null;
  allowed_transitions: BugStatus[];
  can_override_severity: boolean;
  can_assign: boolean;
  can_edit: boolean;
}

export interface BugCreate {
  project_id: number;
  title: string;
  description: string;
  steps_to_reproduce: string;
  environment: string;
  components: string[];
}

export interface BugSearch {
  project_id?: number;
  status?: BugStatus[];
  severity?: Severity[];
  assignee_id?: number;
  reporter_id?: number;
  created_from?: string;
  created_to?: string;
  q?: string;
  sort?: "created_desc" | "created_asc" | "updated_desc" | "severity_desc" | "relevance";
  page?: number;
  page_size?: number;
}

export interface Comment {
  id: number;
  bug_id: number;
  author: UserSummary | null;
  body: string;
  created_at: string;
}

export interface Attachment {
  id: number;
  bug_id: number;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploader: UserSummary | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  action: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  actor: UserSummary | null;
  created_at: string;
}

export interface TriageResponse {
  ai_status: AiStatus;
  notice: string | null;
  duplicates: DuplicateMatch[];
  is_likely_duplicate: boolean;
  severity: {
    severity: Severity | null;
    confidence: number | null;
    probabilities: Record<string, number>;
  };
  recommendations: DeveloperSuggestion[];
  steps: Record<string, StepInfo>;
  total_ms: number;
}

export interface AiStatusResponse {
  enabled: boolean;
  state: "disabled" | "loading" | "ready" | "failed";
  error: string | null;
  models: Record<string, string>;
  load_seconds: number | null;
  indexed_reports: number;
}

export interface Dashboard {
  project_id: number;
  total_bugs: number;
  open_bugs: number;
  open_critical: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  over_time: { day: string; created: number; resolved: number }[];
  average_resolution_hours: number | null;
  top_components: { component: string; open_bugs: number }[];
  days: number;
}

export interface Notification {
  id: number;
  kind: "assigned" | "status_changed" | "critical_bug";
  bug_id: number | null;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export type ExperienceLevel = "Junior" | "Mid" | "Senior";
export type Availability = "Available" | "Limited" | "Unavailable";

export interface Profile {
  id: number;
  user: UserSummary;
  skills: string[];
  components: string[];
  languages: string[];
  experience_level: ExperienceLevel;
  availability: Availability;
  max_workload: number;
  active: boolean;
  resolved_count: number;
  is_cold_start: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProfileFields {
  skills?: string[];
  components?: string[];
  languages?: string[];
  experience_level?: ExperienceLevel;
  availability?: Availability;
  max_workload?: number;
  active?: boolean;
}

export interface Setting {
  key: string;
  value: number;
  default: number;
  minimum: number;
  maximum: number;
  type: string;
  unit: string;
  description: string;
  updated_at: string | null;
  updated_by: UserSummary | null;
}

export interface DeveloperStats {
  user: UserSummary;
  profile_id: number | null;
  active: boolean | null;
  is_cold_start: boolean | null;
  alpha: number | null;
  bugs_resolved: number;
  average_resolution_hours: number | null;
  reassignment_count: number;
  current_workload: number;
  max_workload: number | null;
}
