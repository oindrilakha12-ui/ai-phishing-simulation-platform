export type Role = "super_admin" | "org_admin" | "manager" | "learner";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  org_id: string;
  department_id: string | null;
  is_active: boolean;
  totp_enabled: boolean;
  leaderboard_opt_in: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface SessionInfo {
  user: User;
  org_name: string;
  csrf_token: string;
  demo_mode: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Kpis {
  recipients: number;
  previewed: number;
  clicked: number;
  reported: number;
  completed_training: number;
  click_rate: number;
  report_rate: number;
  report_to_click_ratio: number | null;
  completion_rate?: number;
  enrollments?: number;
  time_to_report_median_min?: number | null;
  time_to_report_p90_min?: number | null;
}

export interface Overview {
  kpis: Kpis;
  heatmap: { department_id: string; department: string; month: string; click_rate: number; recipients: number }[];
  departments: (Kpis & { department_id: string; department: string })[];
  trend: { week: string; recipients: number; click_rate: number; report_rate: number }[];
  top_failed_flags: { category: string; count: number }[];
  cohorts: (Kpis & { cohort: string })[];
  synthetic_data: boolean;
}

export interface RedFlag {
  id: string;
  category: string;
  description: string;
  cue: string;
}

export interface Template {
  id: string;
  name: string;
  brand: string;
  category: string;
  difficulty: "easy" | "medium" | "hard";
  subject: string;
  sender_name: string;
  sender_email: string;
  body_html: string;
  red_flags: RedFlag[];
  version: number;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface Campaign {
  id: string;
  name: string;
  description: string;
  status: "draft" | "scheduled" | "active" | "completed";
  template_id: string | null;
  template_name: string | null;
  template_difficulty: string | null;
  department_ids: string[];
  department_names: string[];
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  stats: Kpis | null;
}

export interface Department {
  id: string;
  name: string;
  created_at: string;
}

export interface PreviewLink {
  index: number;
  href: string;
  text: string;
  actual_host: string;
  displayed_host: string | null;
  mismatch: boolean;
}

export interface Preview {
  template_id: string;
  document: string;
  red_flags: RedFlag[];
  links: PreviewLink[];
  landing_page: string;
  watermark: string;
  red_flags_hidden?: boolean;
  /** Inbox only: what the current learner has already done with this simulation. */
  my_actions?: string[];
}

export interface LiveActivityItem {
  at: string;
  kind: "previewed" | "clicked_sim" | "reported" | "completed_training" | "report_submitted";
  label: string;
  actor: string;
  detail: string;
  department: string | null;
  link: string;
}

export interface Indicator {
  id: string;
  title: string;
  severity: "low" | "medium" | "high";
  explanation: string;
  evidence: string;
  category: string;
  llm_note?: string | null;
}

export interface AgentOutput<R = Record<string, unknown>> {
  request_type: string;
  result: R;
  demo_mode: boolean;
  usage: Record<string, unknown>;
  latency_ms: number;
  turns_in_session: number;
}
