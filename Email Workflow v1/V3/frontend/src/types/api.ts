export type ThreadMessage = {
  message_id: string;
  sender: string;
  recipients: string[];
  subject: string;
  sent_at: string | null;
  snippet: string;
  cleaned_body: string;
};

export type ThreadAnalysis = {
  category: string;
  urgency: string;
  summary: string;
  current_status: string;
  next_action: string;
  needs_action_today: boolean;
  should_draft_reply: boolean;
  draft_needs_date: boolean;
  draft_date_reason: string | null;
  draft_needs_attachment: boolean;
  draft_attachment_reason: string | null;
  crm_contact_name: string | null;
  crm_company: string | null;
  crm_opportunity_type: string | null;
  crm_urgency: string | null;
  provider_name: string;
  model_name: string;
  used_fallback: boolean;
  accuracy_percent: number;
  verification_summary: string;
  needs_human_review: boolean;
  review_reason: string | null;
  verifier_provider_name: string;
  verifier_model_name: string;
  verifier_used_fallback: boolean;
  analyzed_at: string | null;
  verified_at: string | null;
};

export type SeenState = {
  seen: boolean;
  seen_version: string;
  seen_at: string | null;
  pinned: boolean;
};

export type ReviewDecision = {
  queue_belongs: string;
  merge_correct: string;
  summary_useful: string;
  next_action_useful: string;
  draft_useful: string;
  crm_useful: string;
  notes: string;
  improvement_tags: string[];
  updated_at: string | null;
};

export type DraftDocument = {
  subject: string;
  body: string;
  provider_name: string;
  model_name: string;
  used_fallback: boolean;
  created_at: string | null;
};

export type EmailThread = {
  thread_id: string;
  subject: string;
  participants: string[];
  message_count: number;
  latest_message_date: string | null;
  security_status: string;
  sensitivity_markers: string[];
  waiting_on_us: boolean;
  resolved_or_closed: boolean;
  relevance_score: number | null;
  relevance_bucket: string | null;
  included_in_ai: boolean;
  ai_decision: string | null;
  ai_decision_reason: string | null;
  analysis_status: string;
  signature: string;
  is_new: boolean;
  messages: ThreadMessage[];
  analysis: ThreadAnalysis | null;
  seen_state: SeenState | null;
  review: ReviewDecision | null;
  latest_draft: DraftDocument | null;
};

export type QueueSummary = {
  top_priorities: string[];
  executive_summary: string;
  next_actions: string[];
  provider_name: string;
  model_name: string;
  used_fallback: boolean;
};

export type ThreadListResponse = {
  threads: EmailThread[];
};

export type QueueDashboardResponse = {
  threads: EmailThread[];
  summary: QueueSummary;
};

export type SyncRunStatus = {
  run_id: number;
  status: string;
  source: string;
  stage: string;
  progress_percent: number;
  status_message: string;
  fetched_message_count: number;
  thread_count: number;
  ai_thread_count: number;
  cancellation_requested: boolean;
  completed_at: string | null;
  queue_summary: QueueSummary | null;
  error_message: string | null;
};

export type SyncResponse = SyncRunStatus & {
  threads: EmailThread[];
};

export type SettingsSummary = {
  environment: string;
  database_url: string;
  ai_default_provider: string;
  thread_analysis_provider: string;
  queue_summary_provider: string;
  draft_provider: string;
  crm_provider: string;
  ai_mode: string;
  local_ai_force_all_threads: boolean;
  local_ai_model: string;
  local_ai_agent_prompt: string;
  ollama_base_url: string;
  ollama_model_thread_analysis: string;
  runtime_settings_updated_at: string | null;
};

export type RuntimeSettingsUpdate = {
  ai_mode: string;
  local_ai_force_all_threads: boolean;
  local_ai_model: string;
  local_ai_agent_prompt: string;
};

export type GmailConnectionStatus = {
  credentials_configured: boolean;
  connected: boolean;
  email_address: string | null;
  credentials_path: string;
  token_path: string;
  connect_url: string | null;
  error_message: string | null;
};
