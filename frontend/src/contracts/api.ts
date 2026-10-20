/**
 * Setu Supply (SIH26251) — Final Proposal Frozen Data Contracts & APIs (Section 11)
 * Role: Person 3 — UI / Device Owner (Workbench, Freshness/Status Display, Capture Adapter & Offline Queue)
 *
 * Covers the 4 Core Opportunities:
 * 1. AI/ML Demand Forecasting (180-day: 120d train / 30d selection / 30d locked test)
 * 2. Constrained GIS Logistics Planning (POST /api/v1/planning-runs)
 * 3. IoT Inventory Tracking & Gateway Capture Adapter (POST /api/v1/observations)
 * 4. Integrated Predictive Management + Deterministic Policy Engine
 * Plus Subordinate Gated Extensions (Section 10): Optional Local Explanation Assistant & Conditional Custody Digest
 */

export type ItemCategory = 'WATER' | 'FOOD' | 'MEDICAL' | 'CLOTHING' | 'SANITATION';

export type QualityPolicy =
  | 'STANDARD_FEFO'
  | 'MEDICAL_QA_QUARANTINE'
  | 'INSPECTION_REQUIRED';

export interface Item {
  item_id: string;
  name: string;
  category: ItemCategory;
  base_unit: string; // e.g., 'PACK', 'L', 'KIT', 'SET', 'BOTTLE'
  pack_name: string;
  pack_size_base: number;
  pack_conversion_version: string;
  mass_kg_per_base: number;
  storage_volume_per_base_m3: number;
  expiry_required: boolean;
  quality_policy: QualityPolicy;
  min_history_days: number;
  cold_chain_max_temp_c?: number;
}

export interface Site {
  site_id: string;
  display_alias: string;
  sector_label: string;
  access_scope: string;
  data_custodian_id: string;
  custodian_name: string;
  fictional_grid_ref: string;
  fictional_xy: { x: number; y: number };
  storage_capacity_m3: number;
  current_used_storage_m3: number;
  default_lead_time_days: number;
  transport_capacity_packs_per_trip: number;
}

export interface SourceRegistryEntry {
  source_id: string;
  source_name: string;
  authoritative_fields: string[];
  owner: string;
  steward: string;
  permitted_use: string;
  refresh_policy: string;
  retention_policy: string;
  mapping_version: string;
  validation_status: 'VERIFIED_AUTHORITATIVE' | 'PROSPECTIVE_ADAPTER' | 'SIMULATED_CAPTURE';
}

export type FreshnessStatus = 'FRESH' | 'AGING' | 'STALE_GATE_ACTIVE';

export interface ScenarioAssumptions {
  scenario_id: string;
  label: string;
  lead_time_days: number;
  review_period_days: number;
  weather_delay_days: number;
  weather_regime: 'NOMINAL_CLEAR' | 'MONSOON_CONVOY_DELAY' | 'HIGH_ALTITUDE_PASS_CLOSURE';
  buffer_policy_pct: number;
  transport_capacity_packs_limit: number;
  storage_headroom_packs_limit: number; // Explicit pack storage headroom for Section 5 illustrative test (e.g. 40 packs)
  closed_edge_ids: string[];
}

export interface SiteSnapshot {
  snapshot_id: string;
  site_id: string;
  version: number;
  as_of_time: string;
  synced_at: string;
  last_physical_count_at: string;
  freshness_status: FreshnessStatus;
  source_versions: Record<string, string>;
  graph_version: string;
  policy_version: string;
  demand_cutoff: string;
  model_run_ids: string[];
  scenario_assumptions: ScenarioAssumptions;
  data_custodian_id: string;
}

export type BatchQualityState = 'USABLE' | 'QUARANTINED' | 'EXPIRED' | 'DAMAGED';

export interface Batch {
  batch_id: string;
  item_id: string;
  site_id: string;
  expiry_date: string | null;
  quality_state: BatchQualityState;
  physical_qty_base: number;
  damaged_qty_base: number;
  quarantined_qty_base: number;
  expired_qty_base: number;
  quarantine_reason?: string;
  qa_released_by?: string;
  last_verified_at: string;
}

export interface InventoryProjection {
  site_id: string;
  item_id: string;
  snapshot_version: number;
  as_of_time: string;
  synced_at: string;
  last_physical_count_at: string;
  observation_age_hours: number;
  is_stale: boolean;
  physical_on_hand_base: number;
  expired_qty_base: number;
  damaged_qty_base: number;
  quarantined_qty_base: number;
  quality_unavailable_base: number; // UNION of expired, damaged, quarantined
  usable_on_hand_base: number; // physical - quality_unavailable
  active_reserved_base: number;
  allocatable_base: number; // usable - active_reserved
  confirmed_inbound_base: number;
  inbound_arrival_date: string | null;
  inbound_confirmation_status: 'NONE' | 'DISPATCH_RECORDED' | 'CONFIRMED_IN_TRANSIT';
  open_request_commitment_base: number;
  expiring_within_horizon_base: number;
}

export type InventoryEventType =
  | 'OPENING_BALANCE'
  | 'RECEIPT'
  | 'ISSUE'
  | 'RETURN'
  | 'RESERVATION'
  | 'QUARANTINE'
  | 'QA_RELEASE'
  | 'EXPIRY_FLAG'
  | 'COMPENSATING_ADJUSTMENT'
  | 'PROMOTED_IOT_EVIDENCE';

export interface InventoryEvent {
  event_id: string;
  client_event_id: string;
  schema_version: string;
  item_id: string;
  batch_id: string;
  site_id: string;
  type: InventoryEventType;
  quantity_base: number;
  source_ref: string;
  actor_id: string;
  actor_role: UserRole;
  occurred_at: string;
  recorded_at: string;
  expected_version: number;
  resulting_version: number;
  reason: string;
  linked_observation_id?: string;
}

/**
 * Section 8 & 11 IoT Observation & Device Gateway Contracts
 * "A scan identifies an object; it does not alone prove count, quality or custody transfer."
 * "Require the authorized business event for stock mutation. Repeated RFID detections are observations, not repeated receipts."
 */
export type IoTObservationType =
  | 'barcode_seen'
  | 'qr_tally_scan'
  | 'rfid_epc_pass'
  | 'coldchain_temp_c'
  | 'humidity_rh_pct';

export type CalibrationStatus =
  | 'CALIBRATED'
  | 'CALIBRATION_EXPIRED'
  | 'DRIFT_SUSPECTED';

export interface RegisteredIoTDevice {
  device_id: string;
  device_name: string;
  device_type: 'BARCODE_QR_SCANNER' | 'COLDCHAIN_SENSOR' | 'GATE_RFID_READER';
  assigned_site_id: string;
  gateway_id: string;
  boot_session: string;
  last_sequence: number;
  calibration_status: CalibrationStatus;
  calibration_due_date: string;
  buffer_capacity: number;
  is_simulated: boolean;
}

export type IoTObservationValidationStatus =
  | 'PROVISIONAL'
  | 'QUARANTINED_ANOMALY'
  | 'DUPLICATE_IGNORED'
  | 'PROMOTED_TO_LEDGER_EVENT';

export interface IoTObservation {
  schema_version: '1.0';
  event_id: string;
  device_id: string;
  gateway_id: string;
  boot_session: string;
  sequence: number;
  site_id: string;
  item_id: string;
  batch_id: string;
  observation_type: IoTObservationType;
  value: number;
  unit: string;
  occurred_at: string;
  gateway_time: string;
  calibration_status: CalibrationStatus;
  origin_evidence: string;
  status: IoTObservationValidationStatus;
  anomaly_flags: string[];
  sequence_gap_detected: boolean;
  is_simulated: boolean;
  promoted_to_event_id?: string;
}

/**
 * Section 7 & 17 Demand & Forecasting Contracts (180-day: 120d train, 30d selection, 30d locked test)
 */
export interface DemandObservation {
  item_id: string;
  site_id: string;
  date: string;
  day_number: number; // 1..180
  split_window: 'TRAIN_120D' | 'SELECTION_30D' | 'LOCKED_TEST_30D';
  requested_base: number | null;
  issued_base: number | null;
  returned_base: number;
  actual_consumed_if_known_base: number | null;
  unmet_base: number;
  missing_flag: boolean;
  stockout_flag: boolean;
}

export type ForecastModelVersion =
  | 'SEASONAL_NAIVE_7D_V1'
  | 'EWMA_ALPHA_03_V1'
  | 'CROSTON_SBA_CHALLENGER_V1'
  | 'POOLED_MANUAL_FALLBACK_V1';

export type RangeMethod =
  | 'SCENARIO_ENVELOPE_UNCALIBRATED'
  | 'EMPIRICAL_RESIDUAL_ENVELOPE';

export interface ForecastDayPoint {
  date: string;
  day_index: number;
  seasonal_naive_base: number;
  ewma_base: number;
  croston_sba_base: number;
  selected_base: number;
  lower_base: number;
  upper_base: number;
  projected_usable_stock_base: number;
  projected_expiry_loss_base: number;
  scheduled_inbound_base: number;
}

export interface HoldoutComparisonPoint {
  date: string;
  split_window: 'SELECTION_30D' | 'LOCKED_TEST_30D';
  actual_requested_base: number | null;
  seasonal_naive_pred_base: number;
  ewma_pred_base: number;
  croston_sba_pred_base: number;
  stockout_flag: boolean;
  missing_flag: boolean;
}

export interface ForecastEvaluationMetrics {
  label: 'Synthetic evaluation (120d Train / 30d Selection / 30d Locked Test)';
  train_days: number;
  selection_days: number;
  locked_test_days: number;
  seasonal_naive_mae: number;
  seasonal_naive_wape: number | null;
  seasonal_naive_bias: number;
  ewma_mae: number;
  ewma_wape: number | null;
  ewma_bias: number;
  croston_sba_mae: number;
  croston_sba_wape: number | null;
  croston_sba_bias: number;
  fixed_reorder_shortage_days: number;
  order_up_to_shortage_days: number;
  fill_rate_baseline_pct: number;
  fill_rate_policy_pct: number;
}

export interface ForecastRun {
  run_id: string;
  input_snapshot_id: string;
  dataset_fingerprint: string;
  seed: number;
  cutoff: string;
  item_id: string;
  site_id: string;
  horizon: number;
  point_forecast: number[];
  daily_points: ForecastDayPoint[];
  holdout_series: HoldoutComparisonPoint[];
  range_method: RangeMethod;
  lower: number[];
  upper: number[];
  horizon_cumulative_expected_base: number;
  horizon_cumulative_lower_base: number;
  horizon_cumulative_upper_base: number;
  model_version: ForecastModelVersion;
  freshness: FreshnessStatus;
  minimum_evidence_met: boolean;
  history_days_available: number;
  warnings: string[];
  evaluation: ForecastEvaluationMetrics;
  fallback_mode_active: boolean;
}

/**
 * Section 7 & 11 Constrained GIS Logistics Planning Contracts (POST /api/v1/planning-runs)
 */
export interface GisGraphNode {
  node_id: string;
  label: string;
  role: 'REAR_SUPPLY_HUB' | 'REGIONAL_DEPOT' | 'FORWARD_SITE';
  fictional_xy: { x: number; y: number };
  available_source_stock_packs: Record<string, number>;
}

export interface GisGraphEdge {
  edge_id: string;
  from_node_id: string;
  to_node_id: string;
  corridor_label: string;
  declared_transit_days: number;
  max_capacity_packs_per_Window: number;
  max_mass_kg: number;
  transport_cost_per_pack: number;
  default_status: 'OPEN' | 'RESTRICTED' | 'CLOSED';
}

export interface GisRouteAllocation {
  source_node_id: string;
  source_label: string;
  path_edge_ids: string[];
  route_description: string;
  allocated_packs: number;
  allocated_qty_base: number;
  transit_days: number;
  expected_arrival_date: string;
  transport_cost_score: number;
  binding_constraint: string | null;
}

export interface GISPlan {
  plan_id: string;
  snapshot_id: string;
  graph_version: string;
  scenario_id: string;
  constraints_version: string;
  target_site_id: string;
  item_id: string;
  required_packs: number;
  required_qty_base: number;
  storage_headroom_packs: number;
  allocations: GisRouteAllocation[];
  path_refs: string[];
  arrival_assumptions: string[];
  binding_constraints: string[];
  feasible_first_wave_packs: number;
  split_second_wave_packs: number;
  unmet_packs: number;
  unmet_qty_base: number;
  objective_components: {
    shortage_penalty_weight: number;
    transport_cost_weight: number;
    expiry_penalty_weight: number;
    shortage_Check_score: number;
    transport_cost_score: number;
    expiry_risk_score: number;
    total_weighted_objective: number;
  };
  nearest_source_baseline: {
    source_node_id: string;
    path_edge_id: string;
    baseline_status: 'FEASIBLE' | 'BLOCKED_BY_CLOSURE' | 'CAPACITY_EXCEEDED';
    baseline_delivered_packs: number;
    baseline_unmet_packs: number;
    comparison_summary: string;
  };
  solver_status:
    | 'FEASIBLE_SINGLE_WAVE'
    | 'FEASIBLE_SPLIT_ARRIVAL_REQUIRED'
    | 'PARTIAL_INFEASIBLE_UNMET'
    | 'NO_PLAN_ESTABLISHED';
}

/**
 * Section 9 Deterministic Policy Engine Contract
 */
export type PolicyDecisionOutcome = 'ALLOW' | 'DENY' | 'REQUIRES_REVIEW';

export interface PolicyCheckItem {
  rule_id: string;
  rule_label: string;
  status: 'PASS' | 'REVIEW_FLAG' | 'HARD_FAIL';
  detail: string;
}

export interface PolicyEvaluationResult {
  policy_version: string;
  evaluated_at: string;
  decision: PolicyDecisionOutcome;
  reason_codes: string[];
  required_approvers: UserRole[];
  checks: PolicyCheckItem[];
}

export interface EvidenceToDecisionRecord {
  record_id: string;
  problem_statement: string;
  input_snapshot_id: string;
  alternatives_considered: Array<{
    option_label: string;
    proposed_qty_base: number;
    proposed_packs: number;
    expected_shortage_days: number;
    expected_expiry_risk_base: number;
    rationale: string;
  }>;
  assumptions_summary: string[];
  expected_service_stock_effect: string;
  reviewer_decision: string;
  observed_outcome_status: string;
}

export interface Recommendation {
  recommendation_id: string;
  run_id: string;
  plan_id: string;
  site_id: string;
  item_id: string;
  policy_version: string;
  input_version: number;
  input_snapshot_id: string;
  assumptions: ScenarioAssumptions;
  current_usable_base: number;
  current_reserved_base: number;
  current_allocatable_base: number;
  confirmed_inbound_due_base: number;
  inbound_arrival_assumption: string;
  expiring_in_horizon_base: number;
  expected_horizon_demand_base: number;
  declared_buffer_base: number;
  order_up_to_target_base: number;
  net_available_position_base: number;
  raw_deficit_base: number;
  proposed_qty_base: number;
  proposed_packs: number;
  feasible_qty_base: number;
  feasible_packs: number;
  split_arrival_qty_base: number;
  unmet_constrained_base: number;
  constraint_reason: string | null;
  last_physical_count_at: string;
  observation_age_hours: number;
  demand_model_label: string;
  demand_cutoff: string;
  explanation: string;
  warnings: string[];
  policy_evaluation: PolicyEvaluationResult;
  gis_plan: GISPlan;
  status: 'DRAFT' | 'REQUEST_CREATED' | 'OVERRIDDEN';
  evidence_record: EvidenceToDecisionRecord;
}

export type RequestState =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'APPROVED'
  | 'REJECTED'
  | 'CANCELLED';

export type ReservationState = 'UNRESERVED' | 'RESERVED';

export interface ApprovalDecision {
  decision_id: string;
  request_id: string;
  approver_id: string;
  approver_name: string;
  approver_role: UserRole;
  decision: 'APPROVED' | 'REJECTED' | 'APPROVED_WITH_CHANGE';
  approved_qty_base: number;
  reason: string;
  server_time: string;
  revalidated_snapshot_version: number;
  recomputed_policy_decision: PolicyDecisionOutcome;
}

export interface ReplenishmentRequest {
  request_id: string;
  client_event_id: string;
  creator_id: string;
  creator_name: string;
  creator_role: UserRole;
  site_id: string;
  item_id: string;
  proposed_qty_base: number;
  approved_qty_base: number | null;
  override_reason: string | null;
  state: RequestState;
  reservation_state: ReservationState;
  reserved_qty_base: number;
  expected_version: number;
  created_at: string;
  updated_at: string;
  source_recommendation_id: string;
  source_plan_id?: string;
  freshness_warning_acknowledged: boolean;
  is_provisional_offline?: boolean;
  approval_decision: ApprovalDecision | null;
}

export type ShipmentState =
  | 'CREATED'
  | 'DISPATCH_RECORDED'
  | 'PARTIALLY_RECEIVED'
  | 'RECONCILED'
  | 'EXCEPTION_CLOSED';

export interface ReceiptPart {
  receipt_part_id: string;
  client_event_id: string;
  shipment_line_id: string;
  accepted_base: number;
  damaged_base: number;
  rejected_base: number;
  quarantine_quantity_base: number; // Status subset on physically received goods, never additive
  evidence_ref: string;
  recorded_by: string;
  recorded_at: string;
  notes: string;
  is_provisional_offline?: boolean;
}

export interface ShipmentLine {
  shipment_id: string;
  line_id: string;
  request_id: string;
  site_id: string;
  item_id: string;
  batch_id: string;
  expiry_date: string | null;
  authorized_quantity_base: number;
  dispatched_quantity_base: number;
  dispatched_by: string | null;
  dispatched_at: string | null;
  expected_arrival_date: string;
  state: ShipmentState;
  receipt_parts: ReceiptPart[];
  discrepancy_note: string | null;
  exception_closed_by: string | null;
}

export interface CsvImportCandidateRow {
  row_number: number;
  raw_site_id: string;
  raw_item_id: string;
  raw_batch_id: string;
  raw_event_type: string;
  raw_quantity: number;
  raw_unit: string;
  raw_occurred_at: string;
  raw_source_ref: string;
  client_event_id: string;
  expiry_date?: string;
}

export interface CsvValidationResultRow {
  row: CsvImportCandidateRow;
  status: 'VALID' | 'QUARANTINED_ERROR';
  converted_qty_base: number | null;
  error_code?: string;
  error_reason?: string;
}

export interface ImportValidationPreview {
  validation_id: string;
  site_id: string;
  source_id: string;
  created_at: string;
  total_rows: number;
  valid_count: number;
  quarantined_count: number;
  rows: CsvValidationResultRow[];
  committed: boolean;
}

export interface AuditRecord {
  audit_id: string;
  site_id: string;
  actor_id: string;
  actor_name: string;
  actor_role: UserRole;
  action: string;
  object_id: string;
  correlation_id: string;
  server_time: string;
  before_version: number;
  after_version: number;
  reason: string;
  outcome: 'COMMITTED' | 'DENIED_403' | 'CONFLICT_409' | 'INVALID_422';
  prev_hash: string;
  entry_hash: string;
}

/**
 * Section 10 Subordinate Extensions:
 * 1. Optional Local SLM/LLM Explanation Layer (Zero mutation privilege, compartment-filtered retrieval)
 * 2. Conditional Permissioned Custody Acknowledgement Digest
 */
export interface SopDocumentChunk {
  doc_id: string;
  version: string;
  title: string;
  allowed_roles: UserRole[];
  allowed_site_ids: string[];
  content: string;
  contains_adversarial_injection?: boolean;
}

export interface LocalAssistantResponse {
  query_id: string;
  mode: 'DETERMINISTIC_TEMPLATE_DEFAULT' | 'LOCAL_ADVISORY_SLM_SIMULATION';
  question: string;
  answer_text: string;
  cited_record_ids: string[];
  cited_sop_docs: string[];
  filtered_out_compartments: string[];
  injection_blocked: boolean;
  mutation_privilege: 'NONE_READ_ONLY';
}

export interface CustodyAcknowledgementDigest {
  digest_id: string;
  scoped_object_ref: string;
  event_type: 'DISPATCH_HANDOVER' | 'RECEIPT_ACKNOWLEDGE' | 'QA_RELEASE_ATTEST';
  site_id: string;
  canonical_commitment_hash: string;
  offchain_evidence_ref: string;
  signer_identity: string;
  recorded_at: string;
  anchor_status: 'ANCHORED_TO_SHARED_LOG' | 'PENDING_VALIDATOR_QUORUM' | 'LOCAL_SIGNED_LOG_ONLY';
}

export type UserRole =
  | 'STOREKEEPER'
  | 'PLANNER'
  | 'SUPPLY_APPROVER'
  | 'MEDICAL_QA_OFFICER'
  | 'DATA_CUSTODIAN'
  | 'AUDITOR';

export interface AuthenticatedPersona {
  user_id: string;
  display_name: string;
  role: UserRole;
  allowed_site_ids: string[];
  default_site_id: string;
  badge_label: string;
}

export type OfflineEvidenceKind =
  | 'DRAFT_REQUEST'
  | 'PHYSICAL_COUNT_ADJUSTMENT'
  | 'RECEIPT_PART'
  | 'IOT_GATEWAY_OBSERVATION'
  | 'SUPERVISED_BLANK_EVIDENCE';

export type OfflineSyncOutcome = 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'CONFLICT';

export interface OfflineEvidenceItem {
  queue_id: string;
  client_event_id: string;
  kind: OfflineEvidenceKind;
  site_id: string;
  item_id: string;
  created_by: string;
  created_by_role: UserRole;
  created_at_local: string;
  expected_version: number;
  payload: Record<string, unknown>;
  summary_text: string;
  status: OfflineSyncOutcome;
  server_message?: string;
  conflict_server_version?: number;
  authority_expired_capture?: boolean;
}

export interface SyncBatchResponse {
  synced_at: string;
  processed_count: number;
  accepted_count: number;
  rejected_count: number;
  conflict_count: number;
  results: Array<{
    queue_id: string;
    client_event_id: string;
    status: OfflineSyncOutcome;
    message: string;
    current_version: number;
  }>;
}

export interface ApiErrorEnvelope {
  code: string;
  message: string;
  field_errors: Record<string, string>;
  correlation_id: string;
  current_version: number;
  http_status: 403 | 409 | 422 | 500;
}

export interface NeedsActionItem {
  task_id: string;
  site_id: string;
  item_id?: string;
  category:
    | 'STALE_DATA_GATE'
    | 'LOW_ALLOCATABLE_STOCK'
    | 'PENDING_INDEPENDENT_APPROVAL'
    | 'PARTIAL_RECEIPT_DISCREPANCY'
    | 'MEDICAL_QA_QUARANTINE'
    | 'IOT_GATEWAY_ANOMALY'
    | 'OFFLINE_SYNC_CONFLICT';
  severity: 'CRITICAL' | 'WARNING' | 'ACTION_REQUIRED';
  title: string;
  description: string;
  owner_role: UserRole;
  owner_label: string;
  detected_at: string;
  target_screen: 'WORKBENCH' | 'IOT_GATEWAY' | 'FORECAST_GIS' | 'APPROVAL_RECEIPT' | 'OFFLINE_AUDIT';
  reference_id: string;
}
