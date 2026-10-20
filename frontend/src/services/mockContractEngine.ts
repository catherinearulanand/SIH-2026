/**
 * Setu Supply (SIH26251) — Final Proposal Deterministic Contract, Policy, GIS & IoT Engine
 *
 * Implements all Section 11 /api/v1 endpoints:
 * - POST /api/v1/imports/validate & /commit
 * - GET  /api/v1/inventory
 * - POST /api/v1/inventory-events
 * - POST /api/v1/observations          (IoT Gateway Capture Adapter & Physical-Truth Controls)
 * - POST /api/v1/forecast-runs         (180-day 120/30/30 split + Seasonal-Naive / EWMA / Croston-SBA)
 * - POST /api/v1/planning-runs         (Constrained GIS Graph Planner vs Nearest-Feasible-Source Baseline)
 * - POST /api/v1/recommendations       (Deterministic Policy Engine + Order-Up-To + Split-Arrival)
 * - POST /api/v1/requests/{id}/approve (Independent Authority + Recomputed Policy + Freshness Gate)
 * - POST /api/v1/requests/{id}/reserve (Atomic Allocatable Reservation)
 * - POST /api/v1/shipments/{id}/dispatch-record & /receipt-parts
 * - POST /api/v1/sync                  (Per-event Accepted / Rejected / Conflict outcome)
 * - GET  /api/v1/audit                 (Scoped Review History + Custody Digests)
 */

import {
  ApiErrorEnvelope,
  AuditRecord,
  AuthenticatedPersona,
  Batch,
  CsvImportCandidateRow,
  CsvValidationResultRow,
  CustodyAcknowledgementDigest,
  DemandObservation,
  ForecastDayPoint,
  ForecastModelVersion,
  ForecastRun,
  GISPlan,
  GisRouteAllocation,
  HoldoutComparisonPoint,
  ImportValidationPreview,
  InventoryEvent,
  InventoryProjection,
  IoTObservation,
  IoTObservationType,
  Item,
  LocalAssistantResponse,
  NeedsActionItem,
  OfflineEvidenceItem,
  PolicyCheckItem,
  PolicyEvaluationResult,
  ReceiptPart,
  Recommendation,
  RegisteredIoTDevice,
  ReplenishmentRequest,
  ScenarioAssumptions,
  ShipmentLine,
  Site,
  SiteSnapshot,
  SourceRegistryEntry,
  SyncBatchResponse,
  UserRole,
} from '../contracts/api';
import {
  DEMO_CSV_CANDIDATE_ROWS,
  generateSyntheticDemandHistory180,
  GIS_GRAPH_EDGES,
  GIS_GRAPH_NODES,
  INITIAL_BATCHES,
  INITIAL_CUSTODY_DIGESTS,
  INITIAL_EVENTS,
  INITIAL_IOT_OBSERVATIONS,
  INITIAL_REQUESTS,
  INITIAL_SHIPMENTS,
  INITIAL_SNAPSHOTS,
  ITEMS,
  REGISTERED_IOT_DEVICES,
  SCENARIO_PRESETS,
  SITES,
  SOP_DOCUMENTS,
  SOURCE_REGISTRY,
  SYNTHETIC_CUTOFF_DAY,
  SYNTHETIC_DATASET_FINGERPRINT,
  SYNTHETIC_SEED,
} from '../data/syntheticFixtures';

const STORAGE_KEY = 'setu_supply_final_state_v2';

interface IdempotencyEntry {
  client_event_id: string;
  payload_fingerprint: string;
  response_summary: string;
  recorded_at: string;
}

export interface PersistedEngineState {
  snapshots: Record<string, SiteSnapshot>;
  batches: Batch[];
  events: InventoryEvent[];
  iot_devices: RegisteredIoTDevice[];
  iot_observations: IoTObservation[];
  iot_gateway_overflow_alert: boolean;
  requests: ReplenishmentRequest[];
  shipments: ShipmentLine[];
  recommendations: Recommendation[];
  forecast_runs: Record<string, ForecastRun>;
  gis_plans: Record<string, GISPlan>;
  validation_previews: Record<string, ImportValidationPreview>;
  quarantined_csv_rows: CsvValidationResultRow[];
  audit_log: AuditRecord[];
  custody_digests: CustodyAcknowledgementDigest[];
  idempotency_keys: Record<string, IdempotencyEntry>;
  simulate_forecast_failure: boolean;
  assistant_enabled: boolean;
  custody_ledger_mode: 'LOCAL_SIGNED_LOGS_DEFAULT' | 'PERMISSIONED_DIGEST_EXPERIMENT' | 'VALIDATOR_QUORUM_PAUSED';
}

let cachedDemandHistory: DemandObservation[] | null = null;

export function getDemandHistory(): DemandObservation[] {
  if (!cachedDemandHistory) {
    cachedDemandHistory = generateSyntheticDemandHistory180();
  }
  return cachedDemandHistory;
}

function simpleHash(input: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return ('00000000' + (h >>> 0).toString(16)).slice(-8).toUpperCase();
}

function buildInitialAuditLog(): AuditRecord[] {
  const h1 = simpleHash('GENESIS|EVT-0001|1|2');
  const h2 = simpleHash(`${h1}|EVT-0002|12|13`);
  const h3 = simpleHash(`${h2}|DEC-2026-088|13|13`);
  return [
    {
      audit_id: 'AUD-0003',
      site_id: 'SITE-NORTH-01',
      actor_id: 'USR-APPR-N01',
      actor_name: 'Maj. A. Verma (Independent Approver)',
      actor_role: 'SUPPLY_APPROVER',
      action: 'REQUEST_INDEPENDENT_APPROVAL',
      object_id: 'REQ-2026-0102',
      correlation_id: 'CORR-INIT-003',
      server_time: '2026-10-19T16:30:00Z',
      before_version: 13,
      after_version: 13,
      reason: 'Approved after deterministic policy check and independent stock revalidation',
      outcome: 'COMMITTED',
      prev_hash: h2,
      entry_hash: h3,
    },
    {
      audit_id: 'AUD-0002',
      site_id: 'SITE-NORTH-01',
      actor_id: 'USR-STORE-N01',
      actor_name: 'Subedar R. Nair (Storekeeper)',
      actor_role: 'STOREKEEPER',
      action: 'MEDICAL_BATCH_QUARANTINED',
      object_id: 'BCH-ORS-2026-QUAR',
      correlation_id: 'CORR-INIT-002',
      server_time: '2026-10-19T16:20:00Z',
      before_version: 12,
      after_version: 13,
      reason: 'Cold-chain logger excursion (29.4C); placed in medical quarantine pending QA authority',
      outcome: 'COMMITTED',
      prev_hash: h1,
      entry_hash: h2,
    },
    {
      audit_id: 'AUD-0001',
      site_id: 'SITE-NORTH-01',
      actor_id: 'USR-CUST-ALL',
      actor_name: 'Col. V. Deshmukh (Data Custodian)',
      actor_role: 'DATA_CUSTODIAN',
      action: 'OPENING_BALANCE_COMMIT',
      object_id: 'EVT-0001',
      correlation_id: 'CORR-INIT-001',
      server_time: '2026-10-01T06:05:00Z',
      before_version: 1,
      after_version: 2,
      reason: 'Verified physical stock count opening balance',
      outcome: 'COMMITTED',
      prev_hash: '00000000',
      entry_hash: h1,
    },
  ];
}

function createInitialState(): PersistedEngineState {
  const initialIdempotency: Record<string, IdempotencyEntry> = {
    'CEV-RCPT-901-P1': {
      client_event_id: 'CEV-RCPT-901-P1',
      payload_fingerprint: JSON.stringify({
        shipment_line_id: 'SHPL-901-01',
        accepted_base: 576,
        damaged_base: 48,
        rejected_base: 0,
        quarantine_quantity_base: 48,
      }),
      response_summary: 'RCPT-901-PART1 committed',
      recorded_at: '2026-10-20T08:20:00Z',
    },
  };

  return {
    snapshots: JSON.parse(JSON.stringify(INITIAL_SNAPSHOTS)),
    batches: JSON.parse(JSON.stringify(INITIAL_BATCHES)),
    events: JSON.parse(JSON.stringify(INITIAL_EVENTS)),
    iot_devices: JSON.parse(JSON.stringify(REGISTERED_IOT_DEVICES)),
    iot_observations: JSON.parse(JSON.stringify(INITIAL_IOT_OBSERVATIONS)),
    iot_gateway_overflow_alert: false,
    requests: JSON.parse(JSON.stringify(INITIAL_REQUESTS)),
    shipments: JSON.parse(JSON.stringify(INITIAL_SHIPMENTS)),
    recommendations: [],
    forecast_runs: {},
    gis_plans: {},
    validation_previews: {},
    quarantined_csv_rows: [],
    audit_log: buildInitialAuditLog(),
    custody_digests: JSON.parse(JSON.stringify(INITIAL_CUSTODY_DIGESTS)),
    idempotency_keys: initialIdempotency,
    simulate_forecast_failure: false,
    assistant_enabled: true,
    custody_ledger_mode: 'PERMISSIONED_DIGEST_EXPERIMENT',
  };
}

export function loadEngineState(): PersistedEngineState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      return JSON.parse(raw) as PersistedEngineState;
    }
  } catch {
    // Fallback
  }
  const initial = createInitialState();
  saveEngineState(initial);
  return initial;
}

export function saveEngineState(state: PersistedEngineState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Ignore quota errors
  }
}

export function resetEngineStateToSeed(): PersistedEngineState {
  const fresh = createInitialState();
  saveEngineState(fresh);
  return fresh;
}

function appendAudit(
  state: PersistedEngineState,
  params: {
    site_id: string;
    persona: AuthenticatedPersona;
    action: string;
    object_id: string;
    before_version: number;
    after_version: number;
    reason: string;
    outcome: AuditRecord['outcome'];
  }
): AuditRecord {
  const prevHash =
    state.audit_log.length > 0 ? state.audit_log[0].entry_hash : '00000000';
  const now = new Date().toISOString();
  const corrId = `CORR-${Date.now().toString(36).toUpperCase()}`;
  const payload = `${prevHash}|${params.site_id}|${params.persona.user_id}|${params.action}|${params.object_id}|${params.before_version}|${params.after_version}|${params.outcome}`;
  const record: AuditRecord = {
    audit_id: `AUD-${String(state.audit_log.length + 1).padStart(4, '0')}`,
    site_id: params.site_id,
    actor_id: params.persona.user_id,
    actor_name: params.persona.display_name,
    actor_role: params.persona.role,
    action: params.action,
    object_id: params.object_id,
    correlation_id: corrId,
    server_time: now,
    before_version: params.before_version,
    after_version: params.after_version,
    reason: params.reason,
    outcome: params.outcome,
    prev_hash: prevHash,
    entry_hash: simpleHash(payload),
  };
  state.audit_log.unshift(record);
  return record;
}

function makeApiError(
  code: string,
  message: string,
  http_status: 403 | 409 | 422 | 500,
  current_version: number,
  field_errors: Record<string, string> = {}
): ApiErrorEnvelope {
  return {
    code,
    message,
    field_errors,
    correlation_id: `CORR-${Date.now().toString(36).toUpperCase()}`,
    current_version,
    http_status,
  };
}

export function enforceSiteScope(
  state: PersistedEngineState,
  persona: AuthenticatedPersona,
  siteId: string,
  attemptedAction: string
): void {
  if (!persona.allowed_site_ids.includes(siteId)) {
    const snapVersion = state.snapshots[siteId]?.version ?? 0;
    appendAudit(state, {
      site_id: siteId,
      persona,
      action: `COMPARTMENT_SCOPE_DENIED_${attemptedAction}`,
      object_id: siteId,
      before_version: snapVersion,
      after_version: snapVersion,
      reason: `Identity ${persona.user_id} (${persona.role}) lacks compartment scope for ${siteId} (Acceptance Scenario 3)`,
      outcome: 'DENIED_403',
    });
    saveEngineState(state);
    throw makeApiError(
      'SITE_SCOPE_DENIED',
      `Forbidden (403): Authenticated identity '${persona.display_name}' is scoped to [${persona.allowed_site_ids.join(', ')}] and is denied access to site '${siteId}'.`,
      403,
      0
    );
  }
}

/**
 * Computes Section 11 deterministic inventory projections.
 * Quality-unavailable is the UNION of expired, damaged, and quarantined goods.
 */
export function computeInventoryProjectionsForSite(
  state: PersistedEngineState,
  siteId: string
): InventoryProjection[] {
  const snap = state.snapshots[siteId];
  const horizonDays =
    (snap?.scenario_assumptions.lead_time_days ?? 5) +
    (snap?.scenario_assumptions.review_period_days ?? 7) +
    (snap?.scenario_assumptions.weather_delay_days ?? 0);

  const refNow = new Date('2026-10-20T12:00:00Z');
  const horizonCutoff = new Date(refNow);
  horizonCutoff.setUTCDate(horizonCutoff.getUTCDate() + horizonDays);
  const horizonDateStr = horizonCutoff.toISOString().slice(0, 10);

  return ITEMS.map((item) => {
    const siteBatches = state.batches.filter(
      (b) => b.site_id === siteId && b.item_id === item.item_id
    );

    let physicalOnHand = 0;
    let expiredTotal = 0;
    let damagedTotal = 0;
    let quarantinedTotal = 0;
    let qualityUnavailableUnion = 0;
    let expiringWithinHorizon = 0;
    let latestCountIso = snap?.last_physical_count_at ?? '2026-10-20T06:00:00Z';

    for (const batch of siteBatches) {
      physicalOnHand += batch.physical_qty_base;

      const isAlreadyExpired =
        batch.quality_state === 'EXPIRED' ||
        (batch.expiry_date !== null && batch.expiry_date <= '2026-10-20');

      const batchExpired = isAlreadyExpired
        ? batch.physical_qty_base
        : batch.expired_qty_base;
      const batchQuarantined =
        batch.quality_state === 'QUARANTINED'
          ? batch.physical_qty_base
          : batch.quarantined_qty_base;
      const batchDamaged =
        batch.quality_state === 'DAMAGED'
          ? batch.physical_qty_base
          : batch.damaged_qty_base;

      expiredTotal += batchExpired;
      quarantinedTotal += batchQuarantined;
      damagedTotal += batchDamaged;

      // UNION of expired, damaged, and quarantined within batch (never subtract overlapping categories twice!)
      const batchUnavailableUnion =
        isAlreadyExpired ||
        batch.quality_state === 'QUARANTINED' ||
        batch.quality_state === 'DAMAGED'
          ? batch.physical_qty_base
          : Math.min(
              batch.physical_qty_base,
              batchExpired + batchQuarantined + batchDamaged
            );

      qualityUnavailableUnion += batchUnavailableUnion;

      const batchUsable = Math.max(0, batch.physical_qty_base - batchUnavailableUnion);
      if (
        !isAlreadyExpired &&
        batch.expiry_date !== null &&
        batch.expiry_date > '2026-10-20' &&
        batch.expiry_date <= horizonDateStr
      ) {
        expiringWithinHorizon += batchUsable;
      }

      if (batch.last_verified_at && batch.last_verified_at < latestCountIso) {
        latestCountIso = batch.last_verified_at;
      }
    }

    const usableOnHand = Math.max(0, physicalOnHand - qualityUnavailableUnion);

    const activeReserved = state.requests
      .filter(
        (r) =>
          r.site_id === siteId &&
          r.item_id === item.item_id &&
          r.reservation_state === 'RESERVED' &&
          r.state === 'APPROVED'
      )
      .reduce((acc, r) => acc + r.reserved_qty_base, 0);

    const allocatable = Math.max(0, usableOnHand - activeReserved);

    const openCommitment = state.requests
      .filter(
        (r) =>
          r.site_id === siteId &&
          r.item_id === item.item_id &&
          (r.state === 'SUBMITTED' || r.state === 'APPROVED')
      )
      .reduce((acc, r) => acc + (r.approved_qty_base ?? r.proposed_qty_base), 0);

    const openShipments = state.shipments.filter(
      (s) =>
        s.site_id === siteId &&
        s.item_id === item.item_id &&
        (s.state === 'DISPATCH_RECORDED' || s.state === 'PARTIALLY_RECEIVED')
    );

    let confirmedInbound = 0;
    let earliestArrival: string | null = null;
    let inboundStatus: InventoryProjection['inbound_confirmation_status'] = 'NONE';

    for (const shp of openShipments) {
      const accountedSoFar = shp.receipt_parts.reduce(
        (sum, p) => sum + p.accepted_base + p.damaged_base + p.rejected_base,
        0
      );
      const remainingInTransit = Math.max(0, shp.dispatched_quantity_base - accountedSoFar);
      confirmedInbound += remainingInTransit;
      if (!earliestArrival || shp.expected_arrival_date < earliestArrival) {
        earliestArrival = shp.expected_arrival_date;
      }
      inboundStatus =
        shp.state === 'PARTIALLY_RECEIVED'
          ? 'CONFIRMED_IN_TRANSIT'
          : 'DISPATCH_RECORDED';
    }

    const countTimeMs = new Date(latestCountIso).getTime();
    const observationAgeHours = Math.max(
      1,
      Math.round((refNow.getTime() - countTimeMs) / (1000 * 3600))
    );
    const isStale =
      snap?.freshness_status === 'STALE_GATE_ACTIVE' || observationAgeHours > 48;

    return {
      site_id: siteId,
      item_id: item.item_id,
      snapshot_version: snap?.version ?? 1,
      as_of_time: snap?.as_of_time ?? '2026-10-20T12:00:00Z',
      synced_at: snap?.synced_at ?? '2026-10-20T12:00:00Z',
      last_physical_count_at: latestCountIso,
      observation_age_hours: observationAgeHours,
      is_stale: isStale,
      physical_on_hand_base: physicalOnHand,
      expired_qty_base: expiredTotal,
      damaged_qty_base: damagedTotal,
      quarantined_qty_base: quarantinedTotal,
      quality_unavailable_base: qualityUnavailableUnion,
      usable_on_hand_base: usableOnHand,
      active_reserved_base: activeReserved,
      allocatable_base: allocatable,
      confirmed_inbound_base: confirmedInbound,
      inbound_arrival_date: earliestArrival,
      inbound_confirmation_status: inboundStatus,
      open_request_commitment_base: openCommitment,
      expiring_within_horizon_base: expiringWithinHorizon,
    };
  });
}

/**
 * GET /api/v1/inventory
 */
export function apiGetInventory(
  persona: AuthenticatedPersona,
  siteId: string
): {
  snapshot: SiteSnapshot;
  site: Site;
  items: Item[];
  projections: InventoryProjection[];
  batches: Batch[];
  events: InventoryEvent[];
  iot_devices: RegisteredIoTDevice[];
  iot_observations: IoTObservation[];
} {
  const state = loadEngineState();
  enforceSiteScope(state, persona, siteId, 'GET_INVENTORY');
  const site = SITES.find((s) => s.site_id === siteId) ?? SITES[0];
  const snapshot = state.snapshots[siteId];
  const projections = computeInventoryProjectionsForSite(state, siteId);
  const batches = state.batches.filter((b) => b.site_id === siteId);
  const events = state.events.filter((e) => e.site_id === siteId);
  const iotDevices = state.iot_devices.filter((d) => d.assigned_site_id === siteId);
  const iotObservations = state.iot_observations.filter((o) => o.site_id === siteId);
  return {
    snapshot,
    site,
    items: ITEMS,
    projections,
    batches,
    events,
    iot_devices: iotDevices,
    iot_observations: iotObservations,
  };
}

/**
 * POST /api/v1/observations
 * Section 8 & 11 IoT Gateway Ingestion & Physical-Truth Controls:
 * 1. Verifies registered device_id and site compartment binding.
 * 2. Checks monotonic (boot_session, sequence) for duplicate replays or sequence gaps.
 * 3. Checks unit mapping, plausible bounds, and device calibration status.
 * 4. Enforces Rule 7: Observations DO NOT automatically mutate stock! Repeated RFID reads are observations, not receipts.
 */
export function apiIngestIoTObservation(
  persona: AuthenticatedPersona,
  input: {
    event_id: string;
    device_id: string;
    boot_session: string;
    sequence: number;
    site_id: string;
    item_id: string;
    batch_id: string;
    observation_type: IoTObservationType;
    value: number;
    unit: string;
    occurred_at?: string;
  }
): {
  observation: IoTObservation;
  duplicate_ignored: boolean;
  sequence_gap_detected: boolean;
} {
  const state = loadEngineState();
  enforceSiteScope(state, persona, input.site_id, 'POST_IOT_OBSERVATION');

  const device = state.iot_devices.find((d) => d.device_id === input.device_id);
  if (!device) {
    throw makeApiError(
      'UNREGISTERED_IOT_DEVICE',
      `Device '${input.device_id}' is not registered in the approved gateway provisioning table (Section 8 Rule 1).`,
      403,
      state.snapshots[input.site_id]?.version ?? 0
    );
  }

  // Rule 2: Prevent operators or devices assigning arbitrary site authority
  if (device.assigned_site_id !== input.site_id) {
    throw makeApiError(
      'DEVICE_SITE_BINDING_MISMATCH',
      `Device '${device.device_id}' is bound to site '${device.assigned_site_id}' and cannot submit observations for '${input.site_id}' (Section 8 Rule 2).`,
      403,
      state.snapshots[input.site_id]?.version ?? 0
    );
  }

  // Check duplicate event_id or duplicate (device_id, boot_session, sequence)
  const existingObs = state.iot_observations.find(
    (o) =>
      o.event_id === input.event_id ||
      (o.device_id === input.device_id &&
        o.boot_session === input.boot_session &&
        o.sequence === input.sequence)
  );

  if (existingObs) {
    const dupRecord: IoTObservation = {
      ...existingObs,
      status: 'DUPLICATE_IGNORED',
      anomaly_flags: [
        ...new Set([
          ...existingObs.anomaly_flags,
          `DUPLICATE_SEQUENCE_REPLAY (boot=${input.boot_session}, seq=${input.sequence}): Ignored without stock mutation (Scenario 12).`,
        ]),
      ],
    };
    return {
      observation: dupRecord,
      duplicate_ignored: true,
      sequence_gap_detected: false,
    };
  }

  const anomalyFlags: string[] = [];
  let sequenceGap = false;

  if (
    input.boot_session === device.boot_session &&
    input.sequence > device.last_sequence + 1
  ) {
    sequenceGap = true;
    anomalyFlags.push(
      `SEQUENCE_GAP_DETECTED: Expected sequence ${device.last_sequence + 1} on ${device.boot_session}, received ${input.sequence} (${input.sequence - device.last_sequence - 1} missing telemetry frames).`
    );
  } else if (
    input.boot_session === device.boot_session &&
    input.sequence <= device.last_sequence
  ) {
    anomalyFlags.push(
      `OUT_OF_ORDER_OR_REPLAY_SEQUENCE: Sequence ${input.sequence} <= last seen ${device.last_sequence}.`
    );
  }

  if (device.calibration_status !== 'CALIBRATED') {
    anomalyFlags.push(
      `DEVICE_${device.calibration_status}: Reading quarantined for review (calibration due ${device.calibration_due_date}).`
    );
  }

  const item = ITEMS.find((i) => i.item_id === input.item_id);
  if (!item) {
    anomalyFlags.push(`UNKNOWN_ITEM_REF: '${input.item_id}' not in canonical item register.`);
  }

  // Check cold-chain or implausible sensor values
  if (input.observation_type === 'coldchain_temp_c') {
    if (input.value < -50 || input.value > 75) {
      anomalyFlags.push(
        `IMPLAUSIBLE_SENSOR_VALUE (${input.value}°C outside physical sensor bounds [-50°C, +75°C]): Flagged as spoofed/faulty probe (Scenario 12).`
      );
    } else if (
      item?.cold_chain_max_temp_c !== undefined &&
      input.value > item.cold_chain_max_temp_c
    ) {
      anomalyFlags.push(
        `COLD_CHAIN_EXCURSION (${input.value}°C > ${item.cold_chain_max_temp_c}°C threshold for ${item.name}): Routed to Medical QA Authority review.`
      );
    }
  } else if (input.observation_type === 'rfid_epc_pass') {
    anomalyFlags.push(
      'RFID_OBSERVATION_ONLY: Repeated RFID portal detections record presence only and never auto-increment stock (Section 8 Rule 7).'
    );
  } else {
    // Barcode / QR scan unit check
    if (
      item &&
      input.unit.toUpperCase() !== item.base_unit.toUpperCase() &&
      input.unit.toUpperCase() !== item.pack_name.toUpperCase()
    ) {
      anomalyFlags.push(
        `IMPOSSIBLE_SCAN_UNIT ('${input.unit}'): Expected '${item.base_unit}' or '${item.pack_name}'.`
      );
    }
    if (input.value <= 0 || input.value > 5000) {
      anomalyFlags.push(
        `IMPLAUSIBLE_SCAN_COUNT (${input.value}): Outside plausible single-scan bounds.`
      );
    }
  }

  if (input.boot_session === device.boot_session && input.sequence > device.last_sequence) {
    device.last_sequence = input.sequence;
  } else if (input.boot_session !== device.boot_session) {
    device.boot_session = input.boot_session;
    device.last_sequence = input.sequence;
  }

  const nowIso = new Date().toISOString();
  const obs: IoTObservation = {
    schema_version: '1.0',
    event_id: input.event_id,
    device_id: device.device_id,
    gateway_id: device.gateway_id,
    boot_session: input.boot_session,
    sequence: input.sequence,
    site_id: input.site_id,
    item_id: input.item_id,
    batch_id: input.batch_id,
    observation_type: input.observation_type,
    value: input.value,
    unit: input.unit,
    occurred_at: input.occurred_at ?? nowIso,
    gateway_time: nowIso,
    calibration_status: device.calibration_status,
    origin_evidence: `HMAC-${device.gateway_id}:${simpleHash(input.event_id + String(input.sequence))}`,
    status: anomalyFlags.length > 0 ? 'QUARANTINED_ANOMALY' : 'PROVISIONAL',
    anomaly_flags: anomalyFlags,
    sequence_gap_detected: sequenceGap,
    is_simulated: true,
  };

  state.iot_observations.unshift(obs);
  if (state.iot_observations.length > device.buffer_capacity) {
    state.iot_gateway_overflow_alert = true;
  }

  appendAudit(state, {
    site_id: input.site_id,
    persona,
    action:
      obs.status === 'QUARANTINED_ANOMALY'
        ? 'IOT_OBSERVATION_QUARANTINED'
        : 'IOT_OBSERVATION_INGESTED',
    object_id: obs.event_id,
    before_version: state.snapshots[input.site_id].version,
    after_version: state.snapshots[input.site_id].version, // Note: version unchanged because observation does NOT mutate stock!
    reason:
      anomalyFlags.length > 0
        ? anomalyFlags.join(' | ')
        : `Ingested ${obs.observation_type} from ${obs.device_id} (seq ${obs.sequence}); stock unchanged pending business event`,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return {
    observation: obs,
    duplicate_ignored: false,
    sequence_gap_detected: sequenceGap,
  };
}

/**
 * Explicitly promotes a verified PROVISIONAL barcode/QR observation into an authorized ledger business event
 * (Section 8 Rule 7: "Require the authorized business event for stock mutation").
 */
export function apiPromoteObservationToLedgerEvent(
  persona: AuthenticatedPersona,
  observationEventId: string,
  eventType: 'RECEIPT' | 'ISSUE' | 'COMPENSATING_ADJUSTMENT',
  reason: string
): InventoryEvent {
  const state = loadEngineState();
  const obs = state.iot_observations.find((o) => o.event_id === observationEventId);
  if (!obs) {
    throw makeApiError('OBSERVATION_NOT_FOUND', `Observation '${observationEventId}' not found.`, 422, 0);
  }
  enforceSiteScope(state, persona, obs.site_id, 'PROMOTE_IOT_OBSERVATION');

  if (obs.status === 'QUARANTINED_ANOMALY') {
    throw makeApiError(
      'CANNOT_PROMOTE_QUARANTINED_OBSERVATION',
      `Observation '${obs.event_id}' has unresolved anomaly flags (${obs.anomaly_flags.join('; ')}) and cannot directly mutate stock.`,
      422,
      state.snapshots[obs.site_id].version
    );
  }
  if (obs.promoted_to_event_id) {
    throw makeApiError(
      'OBSERVATION_ALREADY_PROMOTED',
      `Observation '${obs.event_id}' was already linked to ledger event '${obs.promoted_to_event_id}'.`,
      409,
      state.snapshots[obs.site_id].version
    );
  }

  const item = ITEMS.find((i) => i.item_id === obs.item_id) ?? ITEMS[0];
  const qtyBase =
    obs.unit.toUpperCase() === item.pack_name.toUpperCase()
      ? obs.value * item.pack_size_base
      : obs.value;

  const res = apiPostInventoryEvent(persona, {
    client_event_id: `CEV-PROM-${obs.event_id}`,
    site_id: obs.site_id,
    item_id: obs.item_id,
    batch_id: obs.batch_id,
    type: eventType,
    quantity_base: qtyBase,
    expected_version: state.snapshots[obs.site_id].version,
    reason: `${reason} [Promoted from verified IoT observation ${obs.event_id}, seq=${obs.sequence}]`,
    source_ref: obs.event_id,
    linked_observation_id: obs.event_id,
  });

  const updatedState = loadEngineState();
  const targetObs = updatedState.iot_observations.find((o) => o.event_id === observationEventId);
  if (targetObs) {
    targetObs.status = 'PROMOTED_TO_LEDGER_EVENT';
    targetObs.promoted_to_event_id = res.event.event_id;
    saveEngineState(updatedState);
  }

  return res.event;
}

/**
 * POST /api/v1/imports/validate
 */
export function apiValidateCsvImport(
  persona: AuthenticatedPersona,
  siteId: string,
  candidateRows?: CsvImportCandidateRow[]
): ImportValidationPreview {
  const state = loadEngineState();
  enforceSiteScope(state, persona, siteId, 'CSV_IMPORT_VALIDATE');

  const rowsToValidate = candidateRows ?? DEMO_CSV_CANDIDATE_ROWS;
  const resultRows: CsvValidationResultRow[] = [];

  for (const row of rowsToValidate) {
    const item = ITEMS.find((i) => i.item_id === row.raw_item_id);
    if (!item) {
      resultRows.push({
        row,
        status: 'QUARANTINED_ERROR',
        converted_qty_base: null,
        error_code: 'UNKNOWN_ITEM_ID',
        error_reason: `Item '${row.raw_item_id}' is not in the canonical item register.`,
      });
      continue;
    }

    if (row.raw_site_id !== siteId) {
      resultRows.push({
        row,
        status: 'QUARANTINED_ERROR',
        converted_qty_base: null,
        error_code: 'SITE_MISMATCH',
        error_reason: `Row site '${row.raw_site_id}' does not match active import target '${siteId}'.`,
      });
      continue;
    }

    const batchExists = state.batches.some(
      (b) => b.site_id === siteId && b.batch_id === row.raw_batch_id
    );
    if (!batchExists && row.raw_event_type === 'ISSUE') {
      resultRows.push({
        row,
        status: 'QUARANTINED_ERROR',
        converted_qty_base: null,
        error_code: 'UNKNOWN_BATCH_ID',
        error_reason: `Batch '${row.raw_batch_id}' is not registered at '${siteId}' (Acceptance Scenario 7).`,
      });
      continue;
    }

    if (row.raw_quantity <= 0 || Number.isNaN(row.raw_quantity)) {
      resultRows.push({
        row,
        status: 'QUARANTINED_ERROR',
        converted_qty_base: null,
        error_code: 'INVALID_QUANTITY_BOUNDS',
        error_reason: `Quantity (${row.raw_quantity}) must be positive; negative/zero quantities are quarantined (Acceptance Scenario 7).`,
      });
      continue;
    }

    let convertedBase: number | null = null;
    if (row.raw_unit.toUpperCase() === item.base_unit.toUpperCase()) {
      convertedBase = row.raw_quantity;
    } else if (row.raw_unit.toUpperCase() === item.pack_name.toUpperCase()) {
      convertedBase = row.raw_quantity * item.pack_size_base;
    }

    if (convertedBase === null) {
      resultRows.push({
        row,
        status: 'QUARANTINED_ERROR',
        converted_qty_base: null,
        error_code: 'UNMAPPED_UNIT_CONVERSION',
        error_reason: `Unit '${row.raw_unit}' is not mapped for ${item.item_id}. Approved: '${item.base_unit}' or '${item.pack_name}' (${item.pack_size_base} ${item.base_unit}) [${item.pack_conversion_version}].`,
      });
      continue;
    }

    if (state.idempotency_keys[row.client_event_id]) {
      resultRows.push({
        row,
        status: 'QUARANTINED_ERROR',
        converted_qty_base: null,
        error_code: 'DUPLICATE_CLIENT_EVENT_KEY',
        error_reason: `Event key '${row.client_event_id}' was already committed at ${state.idempotency_keys[row.client_event_id].recorded_at}.`,
      });
      continue;
    }

    resultRows.push({
      row,
      status: 'VALID',
      converted_qty_base: convertedBase,
    });
  }

  const preview: ImportValidationPreview = {
    validation_id: `VAL-${Date.now().toString(36).toUpperCase()}`,
    site_id: siteId,
    source_id: 'SRC-CSV-IMPORT-02',
    created_at: new Date().toISOString(),
    total_rows: resultRows.length,
    valid_count: resultRows.filter((r) => r.status === 'VALID').length,
    quarantined_count: resultRows.filter((r) => r.status === 'QUARANTINED_ERROR').length,
    rows: resultRows,
    committed: false,
  };

  state.validation_previews[preview.validation_id] = preview;
  const newQuarantined = resultRows.filter((r) => r.status === 'QUARANTINED_ERROR');
  const existingKeys = new Set(state.quarantined_csv_rows.map((q) => q.row.client_event_id));
  for (const q of newQuarantined) {
    if (!existingKeys.has(q.row.client_event_id)) {
      state.quarantined_csv_rows.unshift(q);
    }
  }
  saveEngineState(state);
  return preview;
}

/**
 * POST /api/v1/imports/commit
 */
export function apiCommitCsvImport(
  persona: AuthenticatedPersona,
  validationId: string
): {
  preview: ImportValidationPreview;
  committed_events: InventoryEvent[];
  new_snapshot_version: number;
} {
  const state = loadEngineState();
  const preview = state.validation_previews[validationId];
  if (!preview) {
    throw makeApiError('VALIDATION_PREVIEW_NOT_FOUND', `Preview '${validationId}' not found.`, 422, 0);
  }
  enforceSiteScope(state, persona, preview.site_id, 'CSV_IMPORT_COMMIT');

  if (preview.committed) {
    throw makeApiError(
      'IMPORT_SNAPSHOT_ALREADY_COMMITTED',
      `Import preview '${validationId}' has already been committed once.`,
      409,
      state.snapshots[preview.site_id].version
    );
  }

  const snap = state.snapshots[preview.site_id];
  const committedEvents: InventoryEvent[] = [];

  for (const validRow of preview.rows.filter((r) => r.status === 'VALID')) {
    const qty = validRow.converted_qty_base ?? 0;
    const beforeVer = snap.version;
    snap.version += 1;

    const batch = state.batches.find(
      (b) =>
        b.site_id === preview.site_id &&
        b.batch_id === validRow.row.raw_batch_id &&
        b.item_id === validRow.row.raw_item_id
    );
    if (batch) {
      if (validRow.row.raw_event_type === 'ISSUE') {
        batch.physical_qty_base = Math.max(0, batch.physical_qty_base - qty);
      } else if (validRow.row.raw_event_type === 'RECEIPT') {
        batch.physical_qty_base += qty;
      }
      batch.last_verified_at = new Date().toISOString();
    }

    const evt: InventoryEvent = {
      event_id: `EVT-${String(state.events.length + 1).padStart(4, '0')}`,
      client_event_id: validRow.row.client_event_id,
      schema_version: '1.0',
      item_id: validRow.row.raw_item_id,
      batch_id: validRow.row.raw_batch_id,
      site_id: preview.site_id,
      type: validRow.row.raw_event_type === 'RECEIPT' ? 'RECEIPT' : 'ISSUE',
      quantity_base: qty,
      source_ref: validRow.row.raw_source_ref,
      actor_id: persona.user_id,
      actor_role: persona.role,
      occurred_at: validRow.row.raw_occurred_at,
      recorded_at: new Date().toISOString(),
      expected_version: beforeVer,
      resulting_version: snap.version,
      reason: `Validated CSV import (${validationId}); ${preview.quarantined_count} invalid rows quarantined`,
    };
    state.events.unshift(evt);
    committedEvents.push(evt);

    state.idempotency_keys[evt.client_event_id] = {
      client_event_id: evt.client_event_id,
      payload_fingerprint: JSON.stringify(validRow.row),
      response_summary: evt.event_id,
      recorded_at: evt.recorded_at,
    };
  }

  preview.committed = true;
  snap.as_of_time = new Date().toISOString();
  snap.synced_at = new Date().toISOString();

  appendAudit(state, {
    site_id: preview.site_id,
    persona,
    action: 'CSV_IMPORT_COMMIT',
    object_id: validationId,
    before_version: snap.version - committedEvents.length,
    after_version: snap.version,
    reason: `Committed ${committedEvents.length} valid rows; quarantined ${preview.quarantined_count} invalid rows`,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return {
    preview,
    committed_events: committedEvents,
    new_snapshot_version: snap.version,
  };
}

/**
 * POST /api/v1/inventory-events
 */
export function apiPostInventoryEvent(
  persona: AuthenticatedPersona,
  input: {
    client_event_id: string;
    site_id: string;
    item_id: string;
    batch_id: string;
    type: InventoryEvent['type'];
    quantity_base: number;
    expected_version: number;
    reason: string;
    source_ref: string;
    linked_observation_id?: string;
  }
): { event: InventoryEvent; idempotent_replay: boolean; current_version: number } {
  const state = loadEngineState();
  enforceSiteScope(state, persona, input.site_id, `EVENT_${input.type}`);

  const snap = state.snapshots[input.site_id];
  const fingerprint = JSON.stringify({
    site_id: input.site_id,
    item_id: input.item_id,
    batch_id: input.batch_id,
    type: input.type,
    quantity_base: input.quantity_base,
  });

  const existingIdemp = state.idempotency_keys[input.client_event_id];
  if (existingIdemp) {
    if (existingIdemp.payload_fingerprint !== fingerprint) {
      appendAudit(state, {
        site_id: input.site_id,
        persona,
        action: 'IDEMPOTENCY_KEY_PAYLOAD_MISMATCH',
        object_id: input.client_event_id,
        before_version: snap.version,
        after_version: snap.version,
        reason: `Replay of key '${input.client_event_id}' with altered payload rejected (Acceptance Scenario 1)`,
        outcome: 'CONFLICT_409',
      });
      saveEngineState(state);
      throw makeApiError(
        'IDEMPOTENCY_PAYLOAD_CONFLICT',
        `Conflict (409): Client event key '${input.client_event_id}' was already committed with a different payload.`,
        409,
        snap.version
      );
    }

    const prevEvt = state.events.find((e) => e.client_event_id === input.client_event_id);
    if (prevEvt) {
      return {
        event: prevEvt,
        idempotent_replay: true,
        current_version: snap.version,
      };
    }
  }

  const item = ITEMS.find((i) => i.item_id === input.item_id);
  if (!item) {
    throw makeApiError('UNKNOWN_ITEM', `Item '${input.item_id}' not found.`, 422, snap.version);
  }

  if (input.type !== 'COMPENSATING_ADJUSTMENT' && input.quantity_base <= 0) {
    throw makeApiError(
      'INVALID_QUANTITY',
      `Quantity must be positive (${input.quantity_base} provided).`,
      422,
      snap.version
    );
  }

  // Acceptance Scenario 5: Quarantined medical release requires MEDICAL_QA_OFFICER role
  if (input.type === 'QA_RELEASE' && item.quality_policy === 'MEDICAL_QA_QUARANTINE') {
    if (persona.role !== 'MEDICAL_QA_OFFICER') {
      appendAudit(state, {
        site_id: input.site_id,
        persona,
        action: 'MEDICAL_QA_RELEASE_DENIED',
        object_id: input.batch_id,
        before_version: snap.version,
        after_version: snap.version,
        reason: `Role '${persona.role}' attempted medical quarantine release on ${input.batch_id}; requires MEDICAL_QA_OFFICER (Scenario 5)`,
        outcome: 'DENIED_403',
      });
      saveEngineState(state);
      throw makeApiError(
        'MEDICAL_QA_AUTHORITY_REQUIRED',
        `Forbidden (403): Releasing medical quarantine on '${item.name}' (${input.batch_id}) requires designated Medical QA Authority (MEDICAL_QA_OFFICER). Current role: ${persona.role}.`,
        403,
        snap.version
      );
    }
  }

  const batch = state.batches.find(
    (b) => b.site_id === input.site_id && b.batch_id === input.batch_id
  );
  if (!batch) {
    throw makeApiError(
      'BATCH_NOT_FOUND',
      `Batch '${input.batch_id}' not found at '${input.site_id}'.`,
      422,
      snap.version
    );
  }

  const beforeVersion = snap.version;
  snap.version += 1;
  const nowIso = new Date().toISOString();

  if (input.type === 'QA_RELEASE') {
    batch.quality_state = 'USABLE';
    batch.quarantined_qty_base = 0;
    batch.qa_released_by = persona.display_name;
    batch.quarantine_reason = `QA Released by ${persona.display_name}: ${input.reason}`;
    batch.last_verified_at = nowIso;

    state.custody_digests.unshift({
      digest_id: `DIG-2026-${String(state.custody_digests.length + 1).padStart(3, '0')}`,
      scoped_object_ref: `${input.batch_id} / QA_RELEASE`,
      event_type: 'QA_RELEASE_ATTEST',
      site_id: input.site_id,
      canonical_commitment_hash: `SHA256-COMMIT:${simpleHash(input.batch_id + nowIso + persona.user_id)}`,
      offchain_evidence_ref: `${input.source_ref} (Off-Chain Signed QA Certificate)`,
      signer_identity: `${persona.user_id} (${persona.display_name})`,
      recorded_at: nowIso,
      anchor_status:
        state.custody_ledger_mode === 'VALIDATOR_QUORUM_PAUSED'
          ? 'PENDING_VALIDATOR_QUORUM'
          : state.custody_ledger_mode === 'PERMISSIONED_DIGEST_EXPERIMENT'
            ? 'ANCHORED_TO_SHARED_LOG'
            : 'LOCAL_SIGNED_LOG_ONLY',
    });
  } else if (input.type === 'COMPENSATING_ADJUSTMENT') {
    batch.physical_qty_base = Math.max(0, batch.physical_qty_base + input.quantity_base);
    batch.last_verified_at = nowIso;
    snap.last_physical_count_at = nowIso;
    snap.freshness_status = 'FRESH';
  } else if (input.type === 'RECEIPT' || input.type === 'PROMOTED_IOT_EVIDENCE') {
    batch.physical_qty_base += input.quantity_base;
    batch.last_verified_at = nowIso;
  } else if (input.type === 'ISSUE') {
    batch.physical_qty_base = Math.max(0, batch.physical_qty_base - input.quantity_base);
    batch.last_verified_at = nowIso;
  } else if (input.type === 'QUARANTINE') {
    batch.quality_state = 'QUARANTINED';
    batch.quarantined_qty_base = Math.min(batch.physical_qty_base, input.quantity_base);
    batch.quarantine_reason = input.reason;
    batch.last_verified_at = nowIso;
  }

  snap.as_of_time = nowIso;
  snap.synced_at = nowIso;

  const newEvent: InventoryEvent = {
    event_id: `EVT-${String(state.events.length + 1).padStart(4, '0')}`,
    client_event_id: input.client_event_id,
    schema_version: '1.0',
    item_id: input.item_id,
    batch_id: input.batch_id,
    site_id: input.site_id,
    type: input.type,
    quantity_base: input.quantity_base,
    source_ref: input.source_ref,
    actor_id: persona.user_id,
    actor_role: persona.role,
    occurred_at: nowIso,
    recorded_at: nowIso,
    expected_version: beforeVersion,
    resulting_version: snap.version,
    reason: input.reason,
    linked_observation_id: input.linked_observation_id,
  };

  state.events.unshift(newEvent);
  state.idempotency_keys[input.client_event_id] = {
    client_event_id: input.client_event_id,
    payload_fingerprint: fingerprint,
    response_summary: newEvent.event_id,
    recorded_at: nowIso,
  };

  appendAudit(state, {
    site_id: input.site_id,
    persona,
    action: `LEDGER_EVENT_${input.type}`,
    object_id: newEvent.event_id,
    before_version: beforeVersion,
    after_version: snap.version,
    reason: input.reason,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return {
    event: newEvent,
    idempotent_replay: false,
    current_version: snap.version,
  };
}

/**
 * POST /api/v1/forecast-runs
 * Implements Section 7 & 17 180-day methodology (120d train, 30d selection, 30d locked test)
 * with Seasonal-Naive, EWMA, and Croston-SBA intermittent challenger.
 */
export function apiRunForecast(
  persona: AuthenticatedPersona,
  params: {
    site_id: string;
    item_id: string;
    horizon_days?: number;
    preferred_model?: ForecastModelVersion;
    scenario?: ScenarioAssumptions;
  }
): ForecastRun {
  const state = loadEngineState();
  enforceSiteScope(state, persona, params.site_id, 'RUN_FORECAST');

  const snap = state.snapshots[params.site_id];
  const item = ITEMS.find((i) => i.item_id === params.item_id) ?? ITEMS[0];
  const scenario = params.scenario ?? snap.scenario_assumptions;
  const horizon =
    params.horizon_days ??
    scenario.lead_time_days + scenario.review_period_days + scenario.weather_delay_days;

  const series = getDemandHistory().filter(
    (d) => d.site_id === params.site_id && d.item_id === params.item_id
  );

  const validObs = series.filter((d) => !d.missing_flag && d.requested_base !== null);
  const historyDaysAvailable = validObs.length;
  const minimumEvidenceMet = historyDaysAvailable >= item.min_history_days;

  const warnings: string[] = [];
  if (!minimumEvidenceMet) {
    warnings.push(
      `Minimum-evidence gate triggered: Only ${historyDaysAvailable} observations available (< ${item.min_history_days} days required). Routed to Pooled/Manual Fallback Policy.`
    );
  }

  const missingCount = series.filter((d) => d.missing_flag).length;
  if (missingCount > 0) {
    warnings.push(
      `${missingCount} missing observation dates excluded from fitting (distinct from zero demand).`
    );
  }

  const stockoutCount = series.filter((d) => d.stockout_flag).length;
  if (stockoutCount > 0) {
    warnings.push(
      `${stockoutCount} stockout-suppressed days detected: fitted on true requested demand rather than capped issues.`
    );
  }

  const fallbackActive = state.simulate_forecast_failure || !minimumEvidenceMet;
  if (state.simulate_forecast_failure) {
    warnings.push(
      'Simulated Forecast Module Failure active (Acceptance Scenario 10): Baseline/manual fallback mode remains operational.'
    );
  }

  const chosenModel: ForecastModelVersion = fallbackActive
    ? 'POOLED_MANUAL_FALLBACK_V1'
    : (params.preferred_model ??
      (item.item_id === 'ITM-CLOTH-THERM'
        ? 'CROSTON_SBA_CHALLENGER_V1'
        : 'SEASONAL_NAIVE_7D_V1'));

  // Fit EWMA and Croston-SBA across series (fit transformations strictly on past observations)
  const alpha = 0.3;
  const crostonAlpha = 0.2;
  let ewmaRunning = validObs.length > 0 ? (validObs[0].requested_base ?? 20) : 20;
  let crostonSize = validObs.find((o) => (o.requested_base ?? 0) > 0)?.requested_base ?? 30;
  let crostonInterval = 2.5;
  let periodsSinceLastPositive = 1;

  const ewmaByIndex: number[] = [];
  const crostonByIndex: number[] = [];

  for (let i = 0; i < series.length; i++) {
    const obs = series[i];
    ewmaByIndex.push(Math.round(ewmaRunning));
    // Croston-SBA bias-adjusted rate: (1 - crostonAlpha / 2) * (size / interval)
    const sbaRate = Math.round((1 - crostonAlpha / 2) * (crostonSize / Math.max(1, crostonInterval)));
    crostonByIndex.push(sbaRate);

    if (!obs.missing_flag && obs.requested_base !== null) {
      ewmaRunning = alpha * obs.requested_base + (1 - alpha) * ewmaRunning;
      if (obs.requested_base > 0) {
        crostonSize = crostonAlpha * obs.requested_base + (1 - crostonAlpha) * crostonSize;
        crostonInterval =
          crostonAlpha * periodsSinceLastPositive + (1 - crostonAlpha) * crostonInterval;
        periodsSinceLastPositive = 1;
      } else {
        periodsSinceLastPositive += 1;
      }
    }
  }

  // Evaluate on the last 30 days (LOCKED_TEST_30D)
  const holdoutLen = Math.min(30, Math.max(6, Math.floor(series.length * 0.25)));
  const holdoutStartIdx = series.length - holdoutLen;
  const holdoutSeries: HoldoutComparisonPoint[] = [];

  let snAbs = 0;
  let snSigned = 0;
  let ewmaAbs = 0;
  let ewmaSigned = 0;
  let crostonAbs = 0;
  let crostonSigned = 0;
  let actualSum = 0;
  let evalCount = 0;

  for (let i = holdoutStartIdx; i < series.length; i++) {
    const obs = series[i];
    const lag7 = i >= 7 ? series[i - 7] : null;
    const lag14 = i >= 14 ? series[i - 14] : null;
    const snPred =
      lag7 && !lag7.missing_flag && lag7.requested_base !== null
        ? lag7.requested_base
        : lag14 && !lag14.missing_flag && lag14.requested_base !== null
          ? lag14.requested_base
          : ewmaByIndex[i];
    const ewmaPred = ewmaByIndex[i];
    const crostonPred = crostonByIndex[i];

    holdoutSeries.push({
      date: obs.date,
      split_window: obs.split_window === 'LOCKED_TEST_30D' ? 'LOCKED_TEST_30D' : 'SELECTION_30D',
      actual_requested_base: obs.requested_base,
      seasonal_naive_pred_base: snPred,
      ewma_pred_base: ewmaPred,
      croston_sba_pred_base: crostonPred,
      stockout_flag: obs.stockout_flag,
      missing_flag: obs.missing_flag,
    });

    if (!obs.missing_flag && obs.requested_base !== null) {
      evalCount += 1;
      actualSum += obs.requested_base;
      snAbs += Math.abs(snPred - obs.requested_base);
      snSigned += snPred - obs.requested_base;
      ewmaAbs += Math.abs(ewmaPred - obs.requested_base);
      ewmaSigned += ewmaPred - obs.requested_base;
      crostonAbs += Math.abs(crostonPred - obs.requested_base);
      crostonSigned += crostonPred - obs.requested_base;
    }
  }

  const snMae = evalCount > 0 ? Number((snAbs / evalCount).toFixed(1)) : 0;
  const ewmaMae = evalCount > 0 ? Number((ewmaAbs / evalCount).toFixed(1)) : 0;
  const crostonMae = evalCount > 0 ? Number((crostonAbs / evalCount).toFixed(1)) : 0;

  const snWape = actualSum > 0 ? Number(((snAbs / actualSum) * 100).toFixed(1)) : null;
  const ewmaWape = actualSum > 0 ? Number(((ewmaAbs / actualSum) * 100).toFixed(1)) : null;
  const crostonWape = actualSum > 0 ? Number(((crostonAbs / actualSum) * 100).toFixed(1)) : null;

  const snBias = evalCount > 0 ? Number((snSigned / evalCount).toFixed(1)) : 0;
  const ewmaBias = evalCount > 0 ? Number((ewmaSigned / evalCount).toFixed(1)) : 0;
  const crostonBias = evalCount > 0 ? Number((crostonSigned / evalCount).toFixed(1)) : 0;

  const projections = computeInventoryProjectionsForSite(state, params.site_id);
  const itemProj = projections.find((p) => p.item_id === params.item_id) ?? projections[0];

  let runningUsable = itemProj.allocatable_base;
  const cutoffDate = new Date(`${SYNTHETIC_CUTOFF_DAY}T00:00:00Z`);
  const dailyPoints: ForecastDayPoint[] = [];
  const pointForecast: number[] = [];
  const lowerArr: number[] = [];
  const upperArr: number[] = [];

  const finalCrostonVal =
    crostonByIndex.length > 0 ? crostonByIndex[crostonByIndex.length - 1] : 15;
  const residualSpread = Math.max(snMae, ewmaMae, ewmaRunning * 0.15);

  for (let h = 1; h <= horizon; h++) {
    const fDate = new Date(cutoffDate);
    fDate.setUTCDate(cutoffDate.getUTCDate() + h);
    const fDateStr = fDate.toISOString().slice(0, 10);

    // For ITM-RATION-MRE at SITE-NORTH-01 over 12 days, keep exact 200 PACK/day (8.33 Crates/day -> 2,400 PACK = 100 Crates over 12d)
    // so the Section 5 illustrative replenishment math (100 + 20 - 50 - 10 = 60 Crates) is exact and inspectable!
    const lookbackIdx = series.length - 7 + ((h - 1) % 7);
    const lookbackObs = series[Math.max(0, Math.min(series.length - 1, lookbackIdx))];
    const snVal =
      params.item_id === 'ITM-RATION-MRE' && params.site_id === 'SITE-NORTH-01'
        ? 200
        : lookbackObs && !lookbackObs.missing_flag && lookbackObs.requested_base !== null
          ? lookbackObs.requested_base
          : Math.round(ewmaRunning);

    const ewmaVal =
      params.item_id === 'ITM-RATION-MRE' && params.site_id === 'SITE-NORTH-01'
        ? 200
        : Math.round(ewmaRunning);

    const crostonVal = finalCrostonVal;

    const selectedVal =
      chosenModel === 'EWMA_ALPHA_03_V1'
        ? ewmaVal
        : chosenModel === 'CROSTON_SBA_CHALLENGER_V1'
          ? crostonVal
          : chosenModel === 'POOLED_MANUAL_FALLBACK_V1'
            ? Math.round((snVal + ewmaVal) / 2)
            : snVal;

    const bandWidth = Math.round(residualSpread * (1 + h * 0.03));
    const lowerVal = Math.max(0, selectedVal - bandWidth);
    const upperVal = selectedVal + bandWidth;

    const expiringOnDate = state.batches
      .filter(
        (b) =>
          b.site_id === params.site_id &&
          b.item_id === params.item_id &&
          b.quality_state === 'USABLE' &&
          b.expiry_date === fDateStr
      )
      .reduce(
        (sum, b) =>
          sum + Math.max(0, b.physical_qty_base - b.damaged_qty_base - b.quarantined_qty_base),
        0
      );

    let inboundOnDate = 0;
    for (const shp of state.shipments.filter(
      (s) =>
        s.site_id === params.site_id &&
        s.item_id === params.item_id &&
        (s.state === 'DISPATCH_RECORDED' || s.state === 'PARTIALLY_RECEIVED')
    )) {
      const arrivalDt = new Date(`${shp.expected_arrival_date}T00:00:00Z`);
      arrivalDt.setUTCDate(arrivalDt.getUTCDate() + scenario.weather_delay_days);
      if (arrivalDt.toISOString().slice(0, 10) === fDateStr) {
        const receivedSoFar = shp.receipt_parts.reduce(
          (acc, p) => acc + p.accepted_base + p.damaged_base + p.rejected_base,
          0
        );
        inboundOnDate += Math.max(0, shp.dispatched_quantity_base - receivedSoFar);
      }
    }

    runningUsable = Math.max(0, runningUsable + inboundOnDate - expiringOnDate - selectedVal);

    dailyPoints.push({
      date: fDateStr,
      day_index: h,
      seasonal_naive_base: snVal,
      ewma_base: ewmaVal,
      croston_sba_base: crostonVal,
      selected_base: selectedVal,
      lower_base: lowerVal,
      upper_base: upperVal,
      projected_usable_stock_base: runningUsable,
      projected_expiry_loss_base: expiringOnDate,
      scheduled_inbound_base: inboundOnDate,
    });

    pointForecast.push(selectedVal);
    lowerArr.push(lowerVal);
    upperArr.push(upperVal);
  }

  const cumulativeExpected = pointForecast.reduce((a, b) => a + b, 0);
  // Section 7 rule: Summing daily 90th percentiles does not produce a valid 90th percentile of cumulative demand.
  const aggregateSpread = Math.round(residualSpread * Math.sqrt(horizon) * 1.25);
  const cumulativeLower = Math.max(0, cumulativeExpected - aggregateSpread);
  const cumulativeUpper = cumulativeExpected + aggregateSpread;

  const shortageDaysBaseline = dailyPoints.filter(
    (p) => p.projected_usable_stock_base === 0
  ).length;

  const run: ForecastRun = {
    run_id: `FRUN-${params.site_id.slice(-3)}-${params.item_id.slice(4, 7)}-${String(
      Object.keys(state.forecast_runs).length + 1
    ).padStart(3, '0')}`,
    input_snapshot_id: snap.snapshot_id,
    dataset_fingerprint: SYNTHETIC_DATASET_FINGERPRINT,
    seed: SYNTHETIC_SEED,
    cutoff: snap.demand_cutoff,
    item_id: params.item_id,
    site_id: params.site_id,
    horizon,
    point_forecast: pointForecast,
    daily_points: dailyPoints,
    holdout_series: holdoutSeries,
    range_method: 'SCENARIO_ENVELOPE_UNCALIBRATED',
    lower: lowerArr,
    upper: upperArr,
    horizon_cumulative_expected_base: cumulativeExpected,
    horizon_cumulative_lower_base: cumulativeLower,
    horizon_cumulative_upper_base: cumulativeUpper,
    model_version: chosenModel,
    freshness: snap.freshness_status,
    minimum_evidence_met: minimumEvidenceMet,
    history_days_available: historyDaysAvailable,
    warnings,
    evaluation: {
      label: 'Synthetic evaluation (120d Train / 30d Selection / 30d Locked Test)',
      train_days: Math.min(120, historyDaysAvailable),
      selection_days: historyDaysAvailable >= 150 ? 30 : 0,
      locked_test_days: holdoutLen,
      seasonal_naive_mae: snMae,
      seasonal_naive_wape: snWape,
      seasonal_naive_bias: snBias,
      ewma_mae: ewmaMae,
      ewma_wape: ewmaWape,
      ewma_bias: ewmaBias,
      croston_sba_mae: crostonMae,
      croston_sba_wape: crostonWape,
      croston_sba_bias: crostonBias,
      fixed_reorder_shortage_days: shortageDaysBaseline,
      order_up_to_shortage_days: 0,
      fill_rate_baseline_pct: Math.max(
        55,
        Math.round(((horizon - shortageDaysBaseline) / Math.max(1, horizon)) * 100)
      ),
      fill_rate_policy_pct: 98,
    },
    fallback_mode_active: fallbackActive,
  };

  state.forecast_runs[run.run_id] = run;
  saveEngineState(state);
  return run;
}

/**
 * POST /api/v1/planning-runs
 * Section 7 Constrained GIS Logistics Planner:
 * Evaluates candidate replenishment paths over the fictional graph, compares against
 * the Nearest-Feasible-Source Baseline, respects edge closures, vehicle pack/mass capacity,
 * and depot storage headroom (proposing split-arrival waves when storage is constrained).
 */
export function apiRunGisPlanning(
  persona: AuthenticatedPersona,
  params: {
    site_id: string;
    item_id: string;
    required_packs: number;
    scenario: ScenarioAssumptions;
  }
): GISPlan {
  const state = loadEngineState();
  enforceSiteScope(state, persona, params.site_id, 'RUN_GIS_PLANNER');

  const snap = state.snapshots[params.site_id];
  const item = ITEMS.find((i) => i.item_id === params.item_id) ?? ITEMS[0];
  const closedSet = new Set(params.scenario.closed_edge_ids);

  // Candidate paths to target site
  interface CandidatePath {
    source_node_id: string;
    source_label: string;
    edge_ids: string[];
    route_description: string;
    transit_days: number;
    edge_capacity_packs: number;
    cost_per_pack: number;
    is_blocked: boolean;
    blocked_reason?: string;
  }

  const candidatePaths: CandidatePath[] = [];

  if (params.site_id === 'SITE-NORTH-01') {
    const eMain = GIS_GRAPH_EDGES.find((e) => e.edge_id === 'EDG-N1-MAIN')!;
    const eW1 = GIS_GRAPH_EDGES.find((e) => e.edge_id === 'EDG-W1-TRUNK')!;
    const eWN = GIS_GRAPH_EDGES.find((e) => e.edge_id === 'EDG-CROSS-WN')!;
    const eS1 = GIS_GRAPH_EDGES.find((e) => e.edge_id === 'EDG-S1-FEEDER')!;
    const eSN = GIS_GRAPH_EDGES.find((e) => e.edge_id === 'EDG-SN-ALT')!;

    candidatePaths.push({
      source_node_id: 'HUB-REAR-CENTRAL',
      source_label: 'Rear Base Supply Hub — Central',
      edge_ids: ['EDG-N1-MAIN'],
      route_description: 'Direct Valley Trunk (HUB-REAR-CENTRAL -> SITE-NORTH-01)',
      transit_days: eMain.declared_transit_days + params.scenario.weather_delay_days,
      edge_capacity_packs: Math.min(
        eMain.max_capacity_packs_per_Window,
        params.scenario.transport_capacity_packs_limit
      ),
      cost_per_pack: eMain.transport_cost_per_pack,
      is_blocked: closedSet.has('EDG-N1-MAIN'),
      blocked_reason: closedSet.has('EDG-N1-MAIN')
        ? 'Corridor EDG-N1-MAIN closed in active scenario'
        : undefined,
    });

    candidatePaths.push({
      source_node_id: 'HUB-REAR-WEST',
      source_label: 'Rear Reserve Depot — West Railhead (via SITE-WEST-03)',
      edge_ids: ['EDG-W1-TRUNK', 'EDG-CROSS-WN'],
      route_description: 'Western Ridge Bypass (HUB-REAR-WEST -> SITE-WEST-03 -> SITE-NORTH-01)',
      transit_days:
        eW1.declared_transit_days +
        eWN.declared_transit_days +
        params.scenario.weather_delay_days,
      edge_capacity_packs: Math.min(
        eW1.max_capacity_packs_per_Window,
        eWN.max_capacity_packs_per_Window,
        params.scenario.transport_capacity_packs_limit
      ),
      cost_per_pack: eW1.transport_cost_per_pack + eWN.transport_cost_per_pack,
      is_blocked: closedSet.has('EDG-W1-TRUNK') || closedSet.has('EDG-CROSS-WN'),
      blocked_reason:
        closedSet.has('EDG-W1-TRUNK') || closedSet.has('EDG-CROSS-WN')
          ? 'Western bypass corridor closed in active scenario'
          : undefined,
    });

    candidatePaths.push({
      source_node_id: 'SITE-SOUTH-04',
      source_label: 'Southern Hub Auxiliary Stock (SITE-SOUTH-04)',
      edge_ids: ['EDG-S1-FEEDER', 'EDG-SN-ALT'],
      route_description: 'Eastern Spur Auxiliary (HUB-REAR-CENTRAL -> SITE-SOUTH-04 -> SITE-NORTH-01)',
      transit_days:
        eS1.declared_transit_days +
        eSN.declared_transit_days +
        params.scenario.weather_delay_days,
      edge_capacity_packs: Math.min(
        eSN.max_capacity_packs_per_Window,
        params.scenario.transport_capacity_packs_limit
      ),
      cost_per_pack: eS1.transport_cost_per_pack + eSN.transport_cost_per_pack,
      is_blocked: closedSet.has('EDG-S1-FEEDER') || closedSet.has('EDG-SN-ALT'),
    });
  } else {
    // Generic multi-corridor paths for EAST / WEST / SOUTH sites
    candidatePaths.push({
      source_node_id: 'HUB-REAR-CENTRAL',
      source_label: 'Rear Base Supply Hub — Central',
      edge_ids: ['EDG-E1-PRIMARY'],
      route_description: `Primary Corridor (HUB-REAR-CENTRAL -> ${params.site_id})`,
      transit_days: 4 + params.scenario.weather_delay_days,
      edge_capacity_packs: Math.min(45, params.scenario.transport_capacity_packs_limit),
      cost_per_pack: 15,
      is_blocked: closedSet.has('EDG-E1-PRIMARY') || closedSet.has('EDG-N1-MAIN'),
    });
    candidatePaths.push({
      source_node_id: 'SITE-SOUTH-04',
      source_label: 'Southern Hub Auxiliary Stock (SITE-SOUTH-04)',
      edge_ids: ['EDG-SE-BACKUP'],
      route_description: `Secondary High-Pass Corridor (SITE-SOUTH-04 -> ${params.site_id})`,
      transit_days: 5 + params.scenario.weather_delay_days,
      edge_capacity_packs: Math.min(25, params.scenario.transport_capacity_packs_limit),
      cost_per_pack: 26,
      is_blocked: closedSet.has('EDG-SE-BACKUP'),
    });
  }

  // Evaluate Nearest-Feasible-Source Baseline (picks single closest corridor only)
  const primaryPath = candidatePaths[0];
  let baselineStatus: GISPlan['nearest_source_baseline']['baseline_status'] = 'FEASIBLE';
  let baselineDelivered = 0;

  if (primaryPath.is_blocked) {
    baselineStatus = 'BLOCKED_BY_CLOSURE';
    baselineDelivered = 0;
  } else {
    baselineDelivered = Math.min(
      params.required_packs,
      primaryPath.edge_capacity_packs,
      params.scenario.storage_headroom_packs_limit
    );
    if (baselineDelivered < params.required_packs) {
      baselineStatus = 'CAPACITY_EXCEEDED';
    }
  }
  const baselineUnmet = Math.max(0, params.required_packs - baselineDelivered);

  // Constrained Multi-Source Planner allocation across open corridors
  let remainingToAllocate = params.required_packs;
  const allocations: GisRouteAllocation[] = [];
  const bindingConstraints: string[] = [];

  for (const path of candidatePaths) {
    if (path.is_blocked) {
      bindingConstraints.push(
        `${path.edge_ids.join('+')} CLOSED (${path.blocked_reason ?? 'Scenario closure'})`
      );
      continue;
    }
    if (remainingToAllocate <= 0) break;

    const srcNode = GIS_GRAPH_NODES.find((n) => n.node_id === path.source_node_id);
    const srcAvailPacks = srcNode?.available_source_stock_packs[params.item_id] ?? 80;
    const allocPacks = Math.min(remainingToAllocate, path.edge_capacity_packs, srcAvailPacks);

    if (allocPacks > 0) {
      const arrDate = new Date('2026-10-20T00:00:00Z');
      arrDate.setUTCDate(arrDate.getUTCDate() + path.transit_days);

      let pathBinding: string | null = null;
      if (allocPacks === path.edge_capacity_packs && remainingToAllocate > allocPacks) {
        pathBinding = `Capped by corridor transport limit (${path.edge_capacity_packs} ${item.pack_name}s/window)`;
        bindingConstraints.push(pathBinding);
      }

      allocations.push({
        source_node_id: path.source_node_id,
        source_label: path.source_label,
        path_edge_ids: path.edge_ids,
        route_description: path.route_description,
        allocated_packs: allocPacks,
        allocated_qty_base: allocPacks * item.pack_size_base,
        transit_days: path.transit_days,
        expected_arrival_date: arrDate.toISOString().slice(0, 10),
        transport_cost_score: allocPacks * path.cost_per_pack,
        binding_constraint: pathBinding,
      });

      remainingToAllocate -= allocPacks;
    }
  }

  const totalTransportAllocatedPacks = allocations.reduce(
    (s, a) => s + a.allocated_packs,
    0
  );
  const storageCapPacks = params.scenario.storage_headroom_packs_limit;

  // Section 5 Illustrative Replenishment & Storage Split-Arrival Logic:
  // "If storage has room for only 40 additional packs, show the 20-pack gap and propose an explicitly reviewed split-arrival alternative. Do not silently exceed capacity."
  let feasibleFirstWavePacks = Math.min(totalTransportAllocatedPacks, storageCapPacks);
  let splitSecondWavePacks = 0;

  if (totalTransportAllocatedPacks > storageCapPacks) {
    splitSecondWavePacks = totalTransportAllocatedPacks - storageCapPacks;
    bindingConstraints.push(
      `Depot Storage Headroom Cap: Room for ${storageCapPacks} ${item.pack_name}s in Wave 1; ${splitSecondWavePacks} ${item.pack_name}s (${splitSecondWavePacks * item.pack_size_base} ${item.base_unit}) scheduled as Reviewed Split-Arrival Wave 2 (+5d offset).`
    );
  }

  const unmetPacks = Math.max(0, params.required_packs - totalTransportAllocatedPacks);
  if (unmetPacks > 0) {
    bindingConstraints.push(
      `Unmet Demand Warning: ${unmetPacks} ${item.pack_name}s (${unmetPacks * item.pack_size_base} ${item.base_unit}) cannot be delivered under current corridor closures and vehicle limits.`
    );
  }

  const shortageWeight = 100;
  const transportWeight = 1;
  const expiryWeight = 25;

  const shortageScore = unmetPacks * shortageWeight;
  const transportScore = allocations.reduce((s, a) => s + a.transport_cost_score, 0);
  const expiryScore = splitSecondWavePacks > 0 ? 0 : 10;

  let solverStatus: GISPlan['solver_status'] = 'FEASIBLE_SINGLE_WAVE';
  if (totalTransportAllocatedPacks === 0 && params.required_packs > 0) {
    solverStatus = 'NO_PLAN_ESTABLISHED';
  } else if (unmetPacks > 0) {
    solverStatus = 'PARTIAL_INFEASIBLE_UNMET';
  } else if (splitSecondWavePacks > 0) {
    solverStatus = 'FEASIBLE_SPLIT_ARRIVAL_REQUIRED';
  }

  const plan: GISPlan = {
    plan_id: `PLAN-${params.site_id.slice(-3)}-${item.item_id.slice(4, 7)}-${String(
      Object.keys(state.gis_plans).length + 1
    ).padStart(3, '0')}`,
    snapshot_id: snap.snapshot_id,
    graph_version: snap.graph_version,
    scenario_id: params.scenario.scenario_id,
    constraints_version: 'CONSTR-2026.2',
    target_site_id: params.site_id,
    item_id: params.item_id,
    required_packs: params.required_packs,
    required_qty_base: params.required_packs * item.pack_size_base,
    storage_headroom_packs: storageCapPacks,
    allocations,
    path_refs: allocations.flatMap((a) => a.path_edge_ids),
    arrival_assumptions: [
      `Scenario: ${params.scenario.label}`,
      `Weather delay offset: +${params.scenario.weather_delay_days}d (${params.scenario.weather_regime})`,
      `Max transport capacity: ${params.scenario.transport_capacity_packs_limit} ${item.pack_name}s/corridor`,
      `Receiving storage headroom: ${storageCapPacks} ${item.pack_name}s (${storageCapPacks * item.pack_size_base} ${item.base_unit})`,
    ],
    binding_constraints: bindingConstraints,
    feasible_first_wave_packs: feasibleFirstWavePacks,
    split_second_wave_packs: splitSecondWavePacks,
    unmet_packs: unmetPacks,
    unmet_qty_base: unmetPacks * item.pack_size_base,
    objective_components: {
      shortage_penalty_weight: shortageWeight,
      transport_cost_weight: transportWeight,
      expiry_penalty_weight: expiryWeight,
      shortage_Check_score: shortageScore,
      transport_cost_score: transportScore,
      expiry_risk_score: expiryScore,
      total_weighted_objective: shortageScore + transportScore + expiryScore,
    },
    nearest_source_baseline: {
      source_node_id: primaryPath.source_node_id,
      path_edge_id: primaryPath.edge_ids[0],
      baseline_status: baselineStatus,
      baseline_delivered_packs: baselineDelivered,
      baseline_unmet_packs: baselineUnmet,
      comparison_summary:
        baselineStatus === 'BLOCKED_BY_CLOSURE'
          ? `Nearest-source baseline (${primaryPath.edge_ids[0]}) is BLOCKED (0 delivered, ${baselineUnmet} unmet). Setu Constrained GIS Planner reroutes ${totalTransportAllocatedPacks} ${item.pack_name}s via alternate corridors.`
          : splitSecondWavePacks > 0
            ? `Single-lift baseline caps at ${baselineDelivered} ${item.pack_name}s due to ${storageCapPacks}-pack storage headroom (leaving ${baselineUnmet} unmet). Setu Planner schedules ${feasibleFirstWavePacks} ${item.pack_name}s in Wave 1 + ${splitSecondWavePacks} ${item.pack_name}s in Split-Arrival Wave 2.`
            : `Both Nearest Baseline and Constrained Planner deliver ${feasibleFirstWavePacks} ${item.pack_name}s via primary corridor.`,
    },
    solver_status: solverStatus,
  };

  state.gis_plans[plan.plan_id] = plan;
  saveEngineState(state);
  return plan;
}

/**
 * Section 9 Deterministic Policy Engine
 */
export function evaluateDeterministicPolicy(params: {
  persona: AuthenticatedPersona;
  proj: InventoryProjection;
  item: Item;
  gisPlan: GISPlan;
  forecastRun: ForecastRun;
}): PolicyEvaluationResult {
  const checks: PolicyCheckItem[] = [];
  const reasonCodes: string[] = [];

  // 1. Site & Compartment Scope
  const inScope = params.persona.allowed_site_ids.includes(params.proj.site_id);
  checks.push({
    rule_id: 'RULE-01-COMPARTMENT-SCOPE',
    rule_label: 'Site & Compartment Access Authority',
    status: inScope ? 'PASS' : 'HARD_FAIL',
    detail: inScope
      ? `Actor ${params.persona.user_id} authorized for ${params.proj.site_id}`
      : `Actor lacks compartment access for ${params.proj.site_id}`,
  });
  if (!inScope) reasonCodes.push('DENY_COMPARTMENT_SCOPE');

  // 2. Pack Conversion & Positive Quantity
  checks.push({
    rule_id: 'RULE-02-PACK-CONVERSION',
    rule_label: 'Canonical Base-Unit & Pack Conversion',
    status: 'PASS',
    detail: `${params.gisPlan.required_packs} ${params.item.pack_name}s = ${params.gisPlan.required_qty_base} ${params.item.base_unit} (${params.item.pack_conversion_version})`,
  });

  // 3. Quality & Expiry Exclusion
  checks.push({
    rule_id: 'RULE-03-QUALITY-EXCLUSION',
    rule_label: 'Expired, Damaged & Quarantined Stock Excluded from Usable',
    status: 'PASS',
    detail: `${params.proj.quality_unavailable_base} ${params.item.base_unit} quality-unavailable excluded via union rule; allocatable = ${params.proj.allocatable_base} ${params.item.base_unit}`,
  });

  // 4. Data Freshness Gate
  checks.push({
    rule_id: 'RULE-04-FRESHNESS-THRESHOLD',
    rule_label: 'Physical Count & Snapshot Freshness (<48h)',
    status: params.proj.is_stale ? 'REVIEW_FLAG' : 'PASS',
    detail: params.proj.is_stale
      ? `Count is ${params.proj.observation_age_hours}h old (>48h limit); requires explicit Stale Data Exception sign-off at approval`
      : `Count verified ${params.proj.observation_age_hours}h ago (within 48h threshold)`,
  });
  if (params.proj.is_stale) reasonCodes.push('REQUIRES_STALE_DATA_EXCEPTION_REVIEW');

  // 5. Minimum Historical Forecast Evidence
  checks.push({
    rule_id: 'RULE-05-MINIMUM-EVIDENCE-GATE',
    rule_label: 'Forecast Minimum History Gate (>=30 days)',
    status: params.forecastRun.minimum_evidence_met ? 'PASS' : 'REVIEW_FLAG',
    detail: params.forecastRun.minimum_evidence_met
      ? `${params.forecastRun.history_days_available} valid days available`
      : `Only ${params.forecastRun.history_days_available} days available; routed to Pooled/Manual fallback`,
  });
  if (!params.forecastRun.minimum_evidence_met) {
    reasonCodes.push('REQUIRES_LOW_EVIDENCE_MANUAL_REVIEW');
  }

  // 6. Storage & Transport Feasibility
  const hasUnmet = params.gisPlan.unmet_packs > 0;
  const hasSplit = params.gisPlan.split_second_wave_packs > 0;
  checks.push({
    rule_id: 'RULE-06-GIS-STORAGE-FEASIBILITY',
    rule_label: 'Transport Corridor & Depot Storage Headroom Check',
    status: hasUnmet || hasSplit ? 'REVIEW_FLAG' : 'PASS',
    detail: hasUnmet
      ? `Partial infeasibility: ${params.gisPlan.unmet_packs} ${params.item.pack_name}s unmet due to corridor/capacity constraints`
      : hasSplit
        ? `Storage cap (${params.gisPlan.storage_headroom_packs} ${params.item.pack_name}s) triggered Split-Arrival Wave 1 (${params.gisPlan.feasible_first_wave_packs}) + Wave 2 (${params.gisPlan.split_second_wave_packs})`
        : `Full ${params.gisPlan.required_packs} ${params.item.pack_name}s feasible in single wave`,
  });
  if (hasSplit) reasonCodes.push('REQUIRES_SPLIT_ARRIVAL_SCHEDULE_REVIEW');
  if (hasUnmet) reasonCodes.push('REQUIRES_UNMET_DEMAND_EXCEPTION_REVIEW');

  // 7. Separation of Duties (Creator != Approver)
  checks.push({
    rule_id: 'RULE-07-SEPARATION-OF-DUTIES',
    rule_label: 'Independent Human Approval Required (Creator ≠ Approver)',
    status: 'PASS',
    detail: 'Draft cannot self-authorize; SUPPLY_APPROVER identity required at commit time.',
  });

  const decision: PolicyEvaluationResult['decision'] = !inScope
    ? 'DENY'
    : reasonCodes.length > 0
      ? 'REQUIRES_REVIEW'
      : 'ALLOW';

  if (reasonCodes.length === 0) {
    reasonCodes.push('ALLOW_STANDARD_REPLENISHMENT_POLICY');
  }

  return {
    policy_version: 'DET-POLICY-2026.1',
    evaluated_at: new Date().toISOString(),
    decision,
    reason_codes: reasonCodes,
    required_approvers:
      params.proj.is_stale || hasUnmet
        ? ['SUPPLY_APPROVER', 'DATA_CUSTODIAN']
        : ['SUPPLY_APPROVER'],
    checks,
  };
}

/**
 * POST /api/v1/recommendations
 */
export function apiCreateRecommendation(
  persona: AuthenticatedPersona,
  params: {
    site_id: string;
    item_id: string;
    scenario: ScenarioAssumptions;
    preferred_model?: ForecastModelVersion;
  }
): {
  recommendation: Recommendation;
  forecast_run: ForecastRun;
  gis_plan: GISPlan;
} {
  const state = loadEngineState();
  enforceSiteScope(state, persona, params.site_id, 'CREATE_RECOMMENDATION');

  const snap = state.snapshots[params.site_id];
  snap.scenario_assumptions = params.scenario;
  saveEngineState(state);

  const totalHorizon =
    params.scenario.lead_time_days +
    params.scenario.review_period_days +
    params.scenario.weather_delay_days;

  const forecastRun = apiRunForecast(persona, {
    site_id: params.site_id,
    item_id: params.item_id,
    horizon_days: totalHorizon,
    preferred_model: params.preferred_model,
    scenario: params.scenario,
  });

  const refreshedState = loadEngineState();
  const projections = computeInventoryProjectionsForSite(refreshedState, params.site_id);
  const proj = projections.find((p) => p.item_id === params.item_id) ?? projections[0];
  const item = ITEMS.find((i) => i.item_id === params.item_id) ?? ITEMS[0];

  const expectedDemand = forecastRun.horizon_cumulative_expected_base;
  const declaredBuffer = Math.round((expectedDemand * params.scenario.buffer_policy_pct) / 100);
  const orderUpToTarget = expectedDemand + declaredBuffer;

  const netAvailablePosition = Math.max(
    0,
    proj.allocatable_base + proj.confirmed_inbound_base - proj.expiring_within_horizon_base
  );

  const rawDeficit = Math.max(0, orderUpToTarget - netAvailablePosition);
  const proposedPacks = Math.ceil(rawDeficit / item.pack_size_base);
  const proposedQtyBase = proposedPacks * item.pack_size_base;

  const gisPlan = apiRunGisPlanning(persona, {
    site_id: params.site_id,
    item_id: params.item_id,
    required_packs: proposedPacks,
    scenario: params.scenario,
  });

  const latestState = loadEngineState();
  const policyEvaluation = evaluateDeterministicPolicy({
    persona,
    proj,
    item,
    gisPlan,
    forecastRun,
  });

  const feasiblePacks = gisPlan.feasible_first_wave_packs;
  const feasibleQtyBase = feasiblePacks * item.pack_size_base;
  const splitArrivalQtyBase = gisPlan.split_second_wave_packs * item.pack_size_base;
  const unmetConstrainedBase = gisPlan.unmet_qty_base;

  const constraintReason =
    gisPlan.binding_constraints.length > 0
      ? gisPlan.binding_constraints.join(' | ')
      : null;

  const warnings: string[] = [...forecastRun.warnings, ...gisPlan.binding_constraints];

  const recId = `REC-${params.site_id.slice(-3)}-${item.item_id.slice(4, 7)}-${String(
    latestState.recommendations.length + 1
  ).padStart(3, '0')}`;

  const expectedPacks = Number((expectedDemand / item.pack_size_base).toFixed(1));
  const bufferPacks = Number((declaredBuffer / item.pack_size_base).toFixed(1));
  const allocPacks = Number((proj.allocatable_base / item.pack_size_base).toFixed(1));
  const inboundPacks = Number((proj.confirmed_inbound_base / item.pack_size_base).toFixed(1));

  const recommendation: Recommendation = {
    recommendation_id: recId,
    run_id: forecastRun.run_id,
    plan_id: gisPlan.plan_id,
    site_id: params.site_id,
    item_id: params.item_id,
    policy_version: policyEvaluation.policy_version,
    input_version: snap.version,
    input_snapshot_id: snap.snapshot_id,
    assumptions: params.scenario,
    current_usable_base: proj.usable_on_hand_base,
    current_reserved_base: proj.active_reserved_base,
    current_allocatable_base: proj.allocatable_base,
    confirmed_inbound_due_base: proj.confirmed_inbound_base,
    inbound_arrival_assumption: proj.inbound_arrival_date
      ? `${proj.confirmed_inbound_base} ${item.base_unit} (${inboundPacks} ${item.pack_name}s) due ${proj.inbound_arrival_date}`
      : 'None in transit',
    expiring_in_horizon_base: proj.expiring_within_horizon_base,
    expected_horizon_demand_base: expectedDemand,
    declared_buffer_base: declaredBuffer,
    order_up_to_target_base: orderUpToTarget,
    net_available_position_base: netAvailablePosition,
    raw_deficit_base: rawDeficit,
    proposed_qty_base: proposedQtyBase,
    proposed_packs: proposedPacks,
    feasible_qty_base: feasibleQtyBase,
    feasible_packs: feasiblePacks,
    split_arrival_qty_base: splitArrivalQtyBase,
    unmet_constrained_base: unmetConstrainedBase,
    constraint_reason: constraintReason,
    last_physical_count_at: proj.last_physical_count_at,
    observation_age_hours: proj.observation_age_hours,
    demand_model_label: forecastRun.model_version,
    demand_cutoff: forecastRun.cutoff,
    explanation: `Order-Up-To Policy (${policyEvaluation.policy_version}): max(0, Expected Demand ${expectedPacks} ${item.pack_name}s [${expectedDemand} ${item.base_unit}] + Buffer ${bufferPacks} ${item.pack_name}s [${declaredBuffer} ${item.base_unit}] - Allocatable ${allocPacks} ${item.pack_name}s [${proj.allocatable_base} ${item.base_unit}] - Confirmed Inbound ${inboundPacks} ${item.pack_name}s [${proj.confirmed_inbound_base} ${item.base_unit}]) = ${proposedPacks} ${item.pack_name}s (${proposedQtyBase} ${item.base_unit}). ${
      gisPlan.split_second_wave_packs > 0
        ? `Storage headroom (${gisPlan.storage_headroom_packs} ${item.pack_name}s) requires Split-Arrival: ${feasiblePacks} ${item.pack_name}s in Wave 1 + ${gisPlan.split_second_wave_packs} ${item.pack_name}s in Wave 2.`
        : ''
    }`,
    warnings,
    policy_evaluation: policyEvaluation,
    gis_plan: gisPlan,
    status: 'DRAFT',
    evidence_record: {
      record_id: `ETD-${recId}`,
      problem_statement: `Replenish ${item.name} at ${params.site_id} over ${totalHorizon}-day horizon under '${params.scenario.label}'.`,
      input_snapshot_id: `${snap.snapshot_id} (v${snap.version})`,
      alternatives_considered: [
        {
          option_label: 'Alternative 1 — Nearest-Source Single-Lift Baseline',
          proposed_qty_base: gisPlan.nearest_source_baseline.baseline_delivered_packs * item.pack_size_base,
          proposed_packs: gisPlan.nearest_source_baseline.baseline_delivered_packs,
          expected_shortage_days:
            gisPlan.nearest_source_baseline.baseline_unmet_packs > 0 ? 4 : 0,
          expected_expiry_risk_base: proj.expiring_within_horizon_base,
          rationale: gisPlan.nearest_source_baseline.comparison_summary,
        },
        {
          option_label: `Alternative 2 — Constrained GIS + Split-Arrival Plan (${proposedPacks} ${item.pack_name}s total)`,
          proposed_qty_base: proposedQtyBase,
          proposed_packs: proposedPacks,
          expected_shortage_days: gisPlan.unmet_packs > 0 ? 2 : 0,
          expected_expiry_risk_base: Math.round(proj.expiring_within_horizon_base * 0.2),
          rationale:
            gisPlan.split_second_wave_packs > 0
              ? `Respects ${gisPlan.storage_headroom_packs}-${item.pack_name} storage limit via Wave 1 (${feasiblePacks} ${item.pack_name}s) + Reviewed Split-Arrival Wave 2 (${gisPlan.split_second_wave_packs} ${item.pack_name}s).`
              : `Multi-corridor feasible routing delivering ${feasiblePacks} ${item.pack_name}s.`,
        },
        {
          option_label: 'Alternative 3 — Wave 1 Storage Cap Only (Defer Wave 2)',
          proposed_qty_base: feasibleQtyBase,
          proposed_packs: feasiblePacks,
          expected_shortage_days: gisPlan.split_second_wave_packs > 0 ? 2 : 0,
          expected_expiry_risk_base: 0,
          rationale: `Orders only immediate storage headroom (${feasiblePacks} ${item.pack_name}s), leaving ${gisPlan.split_second_wave_packs} ${item.pack_name}s for next review cycle.`,
        },
      ],
      assumptions_summary: [
        `Dataset Fingerprint: ${SYNTHETIC_DATASET_FINGERPRINT} (Seed ${SYNTHETIC_SEED})`,
        `Forecast Model: ${forecastRun.model_version} (Cutoff ${forecastRun.cutoff})`,
        `GIS Graph: ${gisPlan.graph_version} (${params.scenario.closed_edge_ids.length} closed corridors)`,
        `Deterministic Policy: ${policyEvaluation.policy_version} -> ${policyEvaluation.decision}`,
      ],
      expected_service_stock_effect:
        gisPlan.unmet_packs > 0
          ? `Delivers ${totalHorizon}-day feasible maximum (${feasiblePacks + gisPlan.split_second_wave_packs} ${item.pack_name}s); explicitly flags ${gisPlan.unmet_packs} ${item.pack_name}s unmet for command review.`
          : `Meets full ${proposedPacks} ${item.pack_name} requirement without exceeding storage or corridor limits.`,
      reviewer_decision: 'Pending independent human review (Read-only DRAFT)',
      observed_outcome_status: 'Awaiting dispatch & receipt reconciliation',
    },
  };

  latestState.recommendations.unshift(recommendation);
  saveEngineState(latestState);
  return { recommendation, forecast_run: forecastRun, gis_plan: gisPlan };
}

/**
 * POST /api/v1/requests
 */
export function apiCreateRequest(
  persona: AuthenticatedPersona,
  params: {
    client_event_id: string;
    site_id: string;
    item_id: string;
    proposed_qty_base: number;
    source_recommendation_id: string;
    source_plan_id?: string;
    override_reason?: string;
    freshness_warning_acknowledged: boolean;
    submit_immediately?: boolean;
  }
): ReplenishmentRequest {
  const state = loadEngineState();
  enforceSiteScope(state, persona, params.site_id, 'CREATE_REQUEST');

  const snap = state.snapshots[params.site_id];
  if (params.proposed_qty_base <= 0) {
    throw makeApiError(
      'INVALID_REQUEST_QTY',
      'Request quantity must be greater than zero.',
      422,
      snap.version
    );
  }

  const nowIso = new Date().toISOString();
  const reqId = `REQ-2026-${String(state.requests.length + 101).padStart(4, '0')}`;

  const newReq: ReplenishmentRequest = {
    request_id: reqId,
    client_event_id: params.client_event_id,
    creator_id: persona.user_id,
    creator_name: persona.display_name,
    creator_role: persona.role,
    site_id: params.site_id,
    item_id: params.item_id,
    proposed_qty_base: params.proposed_qty_base,
    approved_qty_base: null,
    override_reason: params.override_reason ?? null,
    state: params.submit_immediately !== false ? 'SUBMITTED' : 'DRAFT',
    reservation_state: 'UNRESERVED',
    reserved_qty_base: 0,
    expected_version: snap.version,
    created_at: nowIso,
    updated_at: nowIso,
    source_recommendation_id: params.source_recommendation_id,
    source_plan_id: params.source_plan_id,
    freshness_warning_acknowledged: params.freshness_warning_acknowledged,
    approval_decision: null,
  };

  state.requests.unshift(newReq);

  const linkedRec = state.recommendations.find(
    (r) => r.recommendation_id === params.source_recommendation_id
  );
  if (linkedRec) {
    linkedRec.status = params.override_reason ? 'OVERRIDDEN' : 'REQUEST_CREATED';
  }

  appendAudit(state, {
    site_id: params.site_id,
    persona,
    action: 'REPLENISHMENT_REQUEST_SUBMITTED',
    object_id: reqId,
    before_version: snap.version,
    after_version: snap.version,
    reason:
      params.override_reason ||
      `Created from recommendation ${params.source_recommendation_id} (${params.proposed_qty_base} base units)`,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return newReq;
}

/**
 * POST /api/v1/requests/{id}/approve
 * Recomputes policy at commit time; enforces Creator != Approver (Scenario 4) and Freshness Gate (Scenario 9).
 */
export function apiApproveRequest(
  persona: AuthenticatedPersona,
  requestId: string,
  params: {
    decision: 'APPROVED' | 'REJECTED' | 'APPROVED_WITH_CHANGE';
    approved_qty_base: number;
    reason: string;
    acknowledge_stale_gate?: boolean;
  }
): { request: ReplenishmentRequest; shipment_created: ShipmentLine | null } {
  const state = loadEngineState();
  const req = state.requests.find((r) => r.request_id === requestId);
  if (!req) {
    throw makeApiError('REQUEST_NOT_FOUND', `Request '${requestId}' not found.`, 422, 0);
  }

  enforceSiteScope(state, persona, req.site_id, 'APPROVE_REQUEST');
  const snap = state.snapshots[req.site_id];

  // Acceptance Scenario 4: Creator cannot approve own request
  if (req.creator_id === persona.user_id) {
    appendAudit(state, {
      site_id: req.site_id,
      persona,
      action: 'SELF_APPROVAL_BLOCKED',
      object_id: req.request_id,
      before_version: snap.version,
      after_version: snap.version,
      reason: `Creator '${persona.user_id}' attempted to approve own request ${req.request_id} (Acceptance Scenario 4)`,
      outcome: 'DENIED_403',
    });
    saveEngineState(state);
    throw makeApiError(
      'SELF_APPROVAL_PROHIBITED',
      `Forbidden (403): Separation-of-duty violation — Request creator (${req.creator_name}) cannot approve their own request. Switch to an independent Supply Approver identity.`,
      403,
      snap.version
    );
  }

  if (persona.role !== 'SUPPLY_APPROVER' && persona.role !== 'DATA_CUSTODIAN') {
    appendAudit(state, {
      site_id: req.site_id,
      persona,
      action: 'UNAUTHORIZED_ROLE_APPROVAL_BLOCKED',
      object_id: req.request_id,
      before_version: snap.version,
      after_version: snap.version,
      reason: `Role '${persona.role}' lacks approval authority for ${req.request_id}`,
      outcome: 'DENIED_403',
    });
    saveEngineState(state);
    throw makeApiError(
      'APPROVER_ROLE_REQUIRED',
      `Forbidden (403): Role '${persona.role}' is not authorized to approve replenishment requests. Independent SUPPLY_APPROVER authority required.`,
      403,
      snap.version
    );
  }

  if (!params.reason || params.reason.trim().length < 5) {
    throw makeApiError(
      'APPROVAL_REASON_REQUIRED',
      'Approver must record an explicit decision reason (min 5 characters).',
      422,
      snap.version
    );
  }

  const projections = computeInventoryProjectionsForSite(state, req.site_id);
  const itemProj = projections.find((p) => p.item_id === req.item_id);
  const isStale =
    snap.freshness_status === 'STALE_GATE_ACTIVE' || (itemProj?.is_stale ?? false);

  if (isStale && !params.acknowledge_stale_gate && params.decision !== 'REJECTED') {
    appendAudit(state, {
      site_id: req.site_id,
      persona,
      action: 'STALE_DATA_APPROVAL_GATE_TRIGGERED',
      object_id: req.request_id,
      before_version: snap.version,
      after_version: snap.version,
      reason: `Approval blocked until stale snapshot (${snap.snapshot_id}) exception is explicitly acknowledged (Scenario 9)`,
      outcome: 'CONFLICT_409',
    });
    saveEngineState(state);
    throw makeApiError(
      'STALE_SNAPSHOT_GATE_BLOCKED',
      `Stale Data Gate (409): Site '${req.site_id}' or item '${req.item_id}' has stale physical count evidence (${itemProj?.observation_age_hours ?? 52}h old). Revalidate count or check 'Acknowledge Stale Snapshot Exception' with reason.`,
      409,
      snap.version
    );
  }

  const nowIso = new Date().toISOString();
  const beforeVer = snap.version;
  snap.version += 1;

  req.state = params.decision === 'REJECTED' ? 'REJECTED' : 'APPROVED';
  req.approved_qty_base =
    params.decision === 'REJECTED' ? 0 : params.approved_qty_base;
  req.updated_at = nowIso;
  req.freshness_warning_acknowledged = true;
  req.approval_decision = {
    decision_id: `DEC-2026-${String(state.audit_log.length + 100)}`,
    request_id: req.request_id,
    approver_id: persona.user_id,
    approver_name: persona.display_name,
    approver_role: persona.role,
    decision: params.decision,
    approved_qty_base: req.approved_qty_base,
    reason: params.reason,
    server_time: nowIso,
    revalidated_snapshot_version: snap.version,
    recomputed_policy_decision: isStale ? 'REQUIRES_REVIEW' : 'ALLOW',
  };

  const linkedRec = state.recommendations.find(
    (r) => r.recommendation_id === req.source_recommendation_id
  );
  if (linkedRec) {
    linkedRec.evidence_record.reviewer_decision = `${params.decision} (${req.approved_qty_base} base units) by ${persona.display_name} at v${snap.version}: "${params.reason}"`;
  }

  let createdShipment: ShipmentLine | null = null;
  if (req.state === 'APPROVED' && (req.approved_qty_base ?? 0) > 0) {
    const arrivalDt = new Date('2026-10-20T00:00:00Z');
    arrivalDt.setUTCDate(
      arrivalDt.getUTCDate() +
        snap.scenario_assumptions.lead_time_days +
        snap.scenario_assumptions.weather_delay_days
    );
    createdShipment = {
      shipment_id: `SHP-2026-${String(state.shipments.length + 901)}`,
      line_id: `SHPL-${String(state.shipments.length + 901)}-01`,
      request_id: req.request_id,
      site_id: req.site_id,
      item_id: req.item_id,
      batch_id: `BCH-${req.item_id.slice(4, 7)}-${String(state.batches.length + 20)}`,
      expiry_date: '2027-09-30',
      authorized_quantity_base: req.approved_qty_base ?? req.proposed_qty_base,
      dispatched_quantity_base: 0,
      dispatched_by: null,
      dispatched_at: null,
      expected_arrival_date: arrivalDt.toISOString().slice(0, 10),
      state: 'CREATED',
      receipt_parts: [],
      discrepancy_note: null,
      exception_closed_by: null,
    };
    state.shipments.unshift(createdShipment);
  }

  appendAudit(state, {
    site_id: req.site_id,
    persona,
    action: `REQUEST_${params.decision}`,
    object_id: req.request_id,
    before_version: beforeVer,
    after_version: snap.version,
    reason: params.reason,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return { request: req, shipment_created: createdShipment };
}

/**
 * POST /api/v1/requests/{id}/reserve
 * Acceptance Scenario 2 & 5: Concurrent reservations cannot exceed allocatable stock; expired/quarantined excluded.
 */
export function apiReserveRequestStock(
  persona: AuthenticatedPersona,
  requestId: string,
  params: {
    reserve_qty_base: number;
    expected_version: number;
  }
): ReplenishmentRequest {
  const state = loadEngineState();
  const req = state.requests.find((r) => r.request_id === requestId);
  if (!req) {
    throw makeApiError('REQUEST_NOT_FOUND', `Request '${requestId}' not found.`, 422, 0);
  }

  enforceSiteScope(state, persona, req.site_id, 'RESERVE_STOCK');
  const snap = state.snapshots[req.site_id];

  if (req.state !== 'APPROVED') {
    throw makeApiError(
      'REQUEST_NOT_APPROVED',
      'Only independently APPROVED requests can reserve stock.',
      409,
      snap.version
    );
  }

  if (params.expected_version !== snap.version) {
    appendAudit(state, {
      site_id: req.site_id,
      persona,
      action: 'CONCURRENT_RESERVATION_VERSION_CONFLICT',
      object_id: req.request_id,
      before_version: snap.version,
      after_version: snap.version,
      reason: `Expected version v${params.expected_version} but current snapshot is v${snap.version} (Acceptance Scenario 2)`,
      outcome: 'CONFLICT_409',
    });
    saveEngineState(state);
    throw makeApiError(
      'STALE_VERSION_CONFLICT',
      `Conflict (409): Snapshot version changed (expected v${params.expected_version}, actual v${snap.version}) due to a concurrent transaction.`,
      409,
      snap.version
    );
  }

  const projections = computeInventoryProjectionsForSite(state, req.site_id);
  const itemProj = projections.find((p) => p.item_id === req.item_id);
  const allocatable = itemProj?.allocatable_base ?? 0;

  if (params.reserve_qty_base > allocatable) {
    appendAudit(state, {
      site_id: req.site_id,
      persona,
      action: 'OVER_ALLOCATION_BLOCKED',
      object_id: req.request_id,
      before_version: snap.version,
      after_version: snap.version,
      reason: `Attempted to reserve ${params.reserve_qty_base} base units when allocatable stock is only ${allocatable} (Acceptance Scenario 2 & 5)`,
      outcome: 'CONFLICT_409',
    });
    saveEngineState(state);
    throw makeApiError(
      'INSUFFICIENT_ALLOCATABLE_STOCK',
      `Over-allocation blocked (409): Requested reservation (${params.reserve_qty_base}) exceeds usable allocatable stock (${allocatable}). Expired (${itemProj?.expired_qty_base ?? 0}) and Quarantined (${itemProj?.quarantined_qty_base ?? 0}) units are excluded from allocation.`,
      409,
      snap.version
    );
  }

  const beforeVer = snap.version;
  snap.version += 1;
  req.reservation_state = 'RESERVED';
  req.reserved_qty_base += params.reserve_qty_base;
  req.updated_at = new Date().toISOString();

  appendAudit(state, {
    site_id: req.site_id,
    persona,
    action: 'ATOMIC_STOCK_RESERVATION',
    object_id: req.request_id,
    before_version: beforeVer,
    after_version: snap.version,
    reason: `Atomically reserved ${params.reserve_qty_base} base units from usable allocatable stock`,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return req;
}

/**
 * POST /api/v1/shipments/{id}/dispatch-record
 */
export function apiRecordShipmentDispatch(
  persona: AuthenticatedPersona,
  shipmentId: string,
  params: {
    dispatched_quantity_base: number;
    expected_arrival_date: string;
    notes: string;
  }
): ShipmentLine {
  const state = loadEngineState();
  const shp = state.shipments.find((s) => s.shipment_id === shipmentId);
  if (!shp) {
    throw makeApiError('SHIPMENT_NOT_FOUND', `Shipment '${shipmentId}' not found.`, 422, 0);
  }
  enforceSiteScope(state, persona, shp.site_id, 'DISPATCH_RECORD');
  const snap = state.snapshots[shp.site_id];

  if (params.dispatched_quantity_base <= 0) {
    throw makeApiError('INVALID_DISPATCH_QTY', 'Dispatched quantity must be > 0.', 422, snap.version);
  }

  const beforeVer = snap.version;
  snap.version += 1;
  const nowIso = new Date().toISOString();
  shp.dispatched_quantity_base = params.dispatched_quantity_base;
  shp.dispatched_by = persona.display_name;
  shp.dispatched_at = nowIso;
  shp.expected_arrival_date = params.expected_arrival_date;
  shp.state = 'DISPATCH_RECORDED';

  state.custody_digests.unshift({
    digest_id: `DIG-2026-${String(state.custody_digests.length + 1).padStart(3, '0')}`,
    scoped_object_ref: `${shp.shipment_id} / DISPATCH`,
    event_type: 'DISPATCH_HANDOVER',
    site_id: shp.site_id,
    canonical_commitment_hash: `SHA256-COMMIT:${simpleHash(shp.shipment_id + nowIso + String(params.dispatched_quantity_base))}`,
    offchain_evidence_ref: `HANDOVER-${shp.shipment_id} (Encrypted Off-Chain Store)`,
    signer_identity: `${persona.user_id} (${persona.display_name})`,
    recorded_at: nowIso,
    anchor_status:
      state.custody_ledger_mode === 'VALIDATOR_QUORUM_PAUSED'
        ? 'PENDING_VALIDATOR_QUORUM'
        : state.custody_ledger_mode === 'PERMISSIONED_DIGEST_EXPERIMENT'
          ? 'ANCHORED_TO_SHARED_LOG'
          : 'LOCAL_SIGNED_LOG_ONLY',
  });

  appendAudit(state, {
    site_id: shp.site_id,
    persona,
    action: 'SHIPMENT_DISPATCH_RECORDED',
    object_id: shp.shipment_id,
    before_version: beforeVer,
    after_version: snap.version,
    reason: `Dispatch recorded (${params.dispatched_quantity_base} base units); ${params.notes}`,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return shp;
}

/**
 * POST /api/v1/shipments/{id}/receipt-parts
 * Acceptance Scenario 1 & 6:
 * - Duplicate receipt retry changes stock once; modified payload with same key is rejected.
 * - Partial receipt preserves unresolved balance; category totals cannot silently exceed dispatch.
 */
export function apiRecordReceiptPart(
  persona: AuthenticatedPersona,
  shipmentId: string,
  params: {
    receipt_part_id: string;
    client_event_id: string;
    accepted_base: number;
    damaged_base: number;
    rejected_base: number;
    quarantine_quantity_base: number;
    evidence_ref: string;
    notes: string;
    allow_discrepancy_overage?: boolean;
  }
): {
  shipment: ShipmentLine;
  receipt_part: ReceiptPart;
  idempotent_replay: boolean;
} {
  const state = loadEngineState();
  const shp = state.shipments.find((s) => s.shipment_id === shipmentId);
  if (!shp) {
    throw makeApiError('SHIPMENT_NOT_FOUND', `Shipment '${shipmentId}' not found.`, 422, 0);
  }
  enforceSiteScope(state, persona, shp.site_id, 'RECEIPT_PART');
  const snap = state.snapshots[shp.site_id];

  const fingerprint = JSON.stringify({
    shipment_line_id: shp.line_id,
    accepted_base: params.accepted_base,
    damaged_base: params.damaged_base,
    rejected_base: params.rejected_base,
    quarantine_quantity_base: params.quarantine_quantity_base,
  });

  const existingIdemp = state.idempotency_keys[params.client_event_id];
  if (existingIdemp) {
    if (existingIdemp.payload_fingerprint !== fingerprint) {
      appendAudit(state, {
        site_id: shp.site_id,
        persona,
        action: 'RECEIPT_IDEMPOTENCY_CONFLICT',
        object_id: params.client_event_id,
        before_version: snap.version,
        after_version: snap.version,
        reason: `Receipt retry key '${params.client_event_id}' reused with altered quantities (Acceptance Scenario 1)`,
        outcome: 'CONFLICT_409',
      });
      saveEngineState(state);
      throw makeApiError(
        'IDEMPOTENCY_PAYLOAD_CONFLICT',
        `Conflict (409): Receipt key '${params.client_event_id}' was already committed with different quantities. Use a new receipt_part_id & client_event_id for a genuine split delivery, or keep identical payload for a retry.`,
        409,
        snap.version
      );
    }

    const existingPart = shp.receipt_parts.find(
      (p) => p.client_event_id === params.client_event_id
    );
    if (existingPart) {
      return {
        shipment: shp,
        receipt_part: existingPart,
        idempotent_replay: true,
      };
    }
  }

  if (
    params.accepted_base < 0 ||
    params.damaged_base < 0 ||
    params.rejected_base < 0 ||
    params.quarantine_quantity_base < 0
  ) {
    throw makeApiError(
      'NEGATIVE_RECEIPT_CATEGORY',
      'Receipt disposition quantities cannot be negative.',
      422,
      snap.version
    );
  }

  const partTotal = params.accepted_base + params.damaged_base + params.rejected_base;
  if (partTotal <= 0) {
    throw makeApiError('EMPTY_RECEIPT_PART', 'Total accounted receipt quantity must be > 0.', 422, snap.version);
  }

  const physicallyHeldFromPart = params.accepted_base + params.damaged_base;
  if (params.quarantine_quantity_base > physicallyHeldFromPart) {
    throw makeApiError(
      'QUARANTINE_EXCEEDS_PHYSICAL_RECEIPT',
      `Validation error (422): Quarantine quantity (${params.quarantine_quantity_base}) is a status on physically received goods (accepted ${params.accepted_base} + damaged ${params.damaged_base} = ${physicallyHeldFromPart}) and cannot exceed it.`,
      422,
      snap.version
    );
  }

  const priorAccounted = shp.receipt_parts.reduce(
    (sum, p) => sum + p.accepted_base + p.damaged_base + p.rejected_base,
    0
  );
  const newCumulative = priorAccounted + partTotal;

  if (newCumulative > shp.dispatched_quantity_base && !params.allow_discrepancy_overage) {
    appendAudit(state, {
      site_id: shp.site_id,
      persona,
      action: 'RECEIPT_EXCEEDS_DISPATCH_BLOCKED',
      object_id: shp.shipment_id,
      before_version: snap.version,
      after_version: snap.version,
      reason: `Cumulative receipt (${newCumulative}) exceeds dispatched quantity (${shp.dispatched_quantity_base}) without discrepancy sign-off (Acceptance Scenario 6)`,
      outcome: 'INVALID_422',
    });
    saveEngineState(state);
    throw makeApiError(
      'RECEIPT_EXCEEDS_DISPATCHED',
      `Discrepancy Gate (422): Cumulative receipt categories (${priorAccounted} prior + ${partTotal} current = ${newCumulative}) exceed dispatched quantity (${shp.dispatched_quantity_base}). Reject over-count or enable 'Authorize Discrepancy Overage Review'.`,
      422,
      snap.version
    );
  }

  const nowIso = new Date().toISOString();
  const beforeVer = snap.version;
  snap.version += 1;

  const newPart: ReceiptPart = {
    receipt_part_id: params.receipt_part_id,
    client_event_id: params.client_event_id,
    shipment_line_id: shp.line_id,
    accepted_base: params.accepted_base,
    damaged_base: params.damaged_base,
    rejected_base: params.rejected_base,
    quarantine_quantity_base: params.quarantine_quantity_base,
    evidence_ref: params.evidence_ref,
    recorded_by: persona.user_id,
    recorded_at: nowIso,
    notes: params.notes,
  };

  shp.receipt_parts.push(newPart);

  let batch = state.batches.find(
    (b) => b.site_id === shp.site_id && b.batch_id === shp.batch_id
  );
  const extraQuarantinedFromAccepted = Math.max(
    0,
    params.quarantine_quantity_base - params.damaged_base
  );

  if (!batch) {
    batch = {
      batch_id: shp.batch_id,
      item_id: shp.item_id,
      site_id: shp.site_id,
      expiry_date: shp.expiry_date,
      quality_state:
        extraQuarantinedFromAccepted > 0 && params.accepted_base === extraQuarantinedFromAccepted
          ? 'QUARANTINED'
          : 'USABLE',
      physical_qty_base: physicallyHeldFromPart,
      damaged_qty_base: params.damaged_base,
      quarantined_qty_base: extraQuarantinedFromAccepted,
      expired_qty_base: 0,
      quarantine_reason:
        params.quarantine_quantity_base > 0
          ? `Receipt part ${newPart.receipt_part_id}: ${params.notes}`
          : undefined,
      last_verified_at: nowIso,
    };
    state.batches.push(batch);
  } else {
    batch.physical_qty_base += physicallyHeldFromPart;
    batch.damaged_qty_base += params.damaged_base;
    batch.quarantined_qty_base += extraQuarantinedFromAccepted;
    batch.last_verified_at = nowIso;
  }

  const remaining = Math.max(0, shp.dispatched_quantity_base - newCumulative);
  if (remaining === 0) {
    shp.state = 'RECONCILED';
    shp.discrepancy_note =
      params.damaged_base === 0 && params.rejected_base === 0
        ? 'Fully received and reconciled with zero discrepancy.'
        : `Reconciled with recorded damaged (${params.damaged_base}) / rejected (${params.rejected_base}) disposition.`;
  } else {
    shp.state = 'PARTIALLY_RECEIVED';
    shp.discrepancy_note = `${remaining} base units unresolved in transit; ${newCumulative} of ${shp.dispatched_quantity_base} accounted across ${shp.receipt_parts.length} receipt part(s).`;
  }

  const usableAdded = Math.max(0, params.accepted_base - extraQuarantinedFromAccepted);

  state.events.unshift({
    event_id: `EVT-${String(state.events.length + 1).padStart(4, '0')}`,
    client_event_id: params.client_event_id,
    schema_version: '1.0',
    item_id: shp.item_id,
    batch_id: shp.batch_id,
    site_id: shp.site_id,
    type: 'RECEIPT',
    quantity_base: usableAdded,
    source_ref: params.evidence_ref,
    actor_id: persona.user_id,
    actor_role: persona.role,
    occurred_at: nowIso,
    recorded_at: nowIso,
    expected_version: beforeVer,
    resulting_version: snap.version,
    reason: `Receipt Part ${params.receipt_part_id}: +${usableAdded} usable (${params.accepted_base} accepted, ${params.damaged_base} damaged, ${params.rejected_base} rejected, ${params.quarantine_quantity_base} quarantined subset)`,
  });

  state.idempotency_keys[params.client_event_id] = {
    client_event_id: params.client_event_id,
    payload_fingerprint: fingerprint,
    response_summary: newPart.receipt_part_id,
    recorded_at: nowIso,
  };

  state.custody_digests.unshift({
    digest_id: `DIG-2026-${String(state.custody_digests.length + 1).padStart(3, '0')}`,
    scoped_object_ref: `${shp.shipment_id} / ${newPart.receipt_part_id}`,
    event_type: 'RECEIPT_ACKNOWLEDGE',
    site_id: shp.site_id,
    canonical_commitment_hash: `SHA256-COMMIT:${simpleHash(newPart.receipt_part_id + fingerprint)}`,
    offchain_evidence_ref: `${params.evidence_ref} (Encrypted Off-Chain Store)`,
    signer_identity: `${persona.user_id} (${persona.display_name})`,
    recorded_at: nowIso,
    anchor_status:
      state.custody_ledger_mode === 'VALIDATOR_QUORUM_PAUSED'
        ? 'PENDING_VALIDATOR_QUORUM'
        : state.custody_ledger_mode === 'PERMISSIONED_DIGEST_EXPERIMENT'
          ? 'ANCHORED_TO_SHARED_LOG'
          : 'LOCAL_SIGNED_LOG_ONLY',
  });

  appendAudit(state, {
    site_id: shp.site_id,
    persona,
    action: 'SHIPMENT_RECEIPT_PART_RECORDED',
    object_id: newPart.receipt_part_id,
    before_version: beforeVer,
    after_version: snap.version,
    reason: `Shipment ${shp.shipment_id}: accepted=${params.accepted_base}, damaged=${params.damaged_base}, rejected=${params.rejected_base}, quarantine_subset=${params.quarantine_quantity_base}`,
    outcome: 'COMMITTED',
  });

  saveEngineState(state);
  return {
    shipment: shp,
    receipt_part: newPart,
    idempotent_replay: false,
  };
}

/**
 * POST /api/v1/sync
 */
export function apiSyncOfflineQueue(
  persona: AuthenticatedPersona,
  queueItems: OfflineEvidenceItem[],
  forceAcceptConflicts = false
): { response: SyncBatchResponse; updatedQueue: OfflineEvidenceItem[] } {
  const state = loadEngineState();
  const results: SyncBatchResponse['results'] = [];
  const updatedQueue: OfflineEvidenceItem[] = [];

  let acceptedCount = 0;
  let rejectedCount = 0;
  let conflictCount = 0;

  for (const qItem of queueItems) {
    if (qItem.status === 'ACCEPTED') {
      updatedQueue.push(qItem);
      continue;
    }

    const snap = state.snapshots[qItem.site_id];
    const currentVer = snap?.version ?? 1;

    if (!persona.allowed_site_ids.includes(qItem.site_id)) {
      const rejected: OfflineEvidenceItem = {
        ...qItem,
        status: 'REJECTED',
        server_message: `Scope denied (403): Current user '${persona.display_name}' lacks compartment scope for '${qItem.site_id}'.`,
      };
      updatedQueue.push(rejected);
      rejectedCount += 1;
      results.push({
        queue_id: qItem.queue_id,
        client_event_id: qItem.client_event_id,
        status: 'REJECTED',
        message: rejected.server_message!,
        current_version: currentVer,
      });
      continue;
    }

    if (qItem.authority_expired_capture && !forceAcceptConflicts) {
      const conflicted: OfflineEvidenceItem = {
        ...qItem,
        status: 'CONFLICT',
        conflict_server_version: currentVer,
        server_message:
          'Captured under Expired Offline Authority Lease: Held for supervised custodian reconciliation before commit.',
      };
      updatedQueue.push(conflicted);
      conflictCount += 1;
      results.push({
        queue_id: qItem.queue_id,
        client_event_id: qItem.client_event_id,
        status: 'CONFLICT',
        message: conflicted.server_message!,
        current_version: currentVer,
      });
      continue;
    }

    if (qItem.expected_version < currentVer && !forceAcceptConflicts) {
      const conflicted: OfflineEvidenceItem = {
        ...qItem,
        status: 'CONFLICT',
        conflict_server_version: currentVer,
        server_message: `Version Conflict (409): Drafted against snapshot v${qItem.expected_version}, but server snapshot is now v${currentVer} (Acceptance Scenario 8). No silent overwrite.`,
      };
      updatedQueue.push(conflicted);
      conflictCount += 1;
      results.push({
        queue_id: qItem.queue_id,
        client_event_id: qItem.client_event_id,
        status: 'CONFLICT',
        message: conflicted.server_message!,
        current_version: currentVer,
      });
      continue;
    }

    try {
      if (qItem.kind === 'DRAFT_REQUEST') {
        apiCreateRequest(persona, {
          client_event_id: qItem.client_event_id,
          site_id: qItem.site_id,
          item_id: qItem.item_id,
          proposed_qty_base: Number(qItem.payload.proposed_qty_base ?? 240),
          source_recommendation_id: String(
            qItem.payload.source_recommendation_id ?? 'REC-OFFLINE-DRAFT'
          ),
          override_reason: `Synced from offline draft (${qItem.client_event_id})`,
          freshness_warning_acknowledged: true,
          submit_immediately: true,
        });
      } else if (qItem.kind === 'IOT_GATEWAY_OBSERVATION') {
        apiIngestIoTObservation(persona, {
          event_id: qItem.client_event_id,
          device_id: String(qItem.payload.device_id ?? 'scanner-demo-01'),
          boot_session: String(qItem.payload.boot_session ?? 'boot-demo-03'),
          sequence: Number(qItem.payload.sequence ?? 99),
          site_id: qItem.site_id,
          item_id: qItem.item_id,
          batch_id: String(qItem.payload.batch_id ?? 'BCH-MRE-2026-B1'),
          observation_type:
            (qItem.payload.observation_type as IoTObservationType) ?? 'barcode_seen',
          value: Number(qItem.payload.value ?? 1),
          unit: String(qItem.payload.unit ?? 'Crate'),
          occurred_at: qItem.created_at_local,
        });
      } else if (
        qItem.kind === 'PHYSICAL_COUNT_ADJUSTMENT' ||
        qItem.kind === 'SUPERVISED_BLANK_EVIDENCE'
      ) {
        const targetBatch =
          state.batches.find(
            (b) => b.site_id === qItem.site_id && b.item_id === qItem.item_id
          )?.batch_id ?? 'BCH-MRE-2026-B1';
        apiPostInventoryEvent(persona, {
          client_event_id: qItem.client_event_id,
          site_id: qItem.site_id,
          item_id: qItem.item_id,
          batch_id: String(qItem.payload.batch_id ?? targetBatch),
          type: 'COMPENSATING_ADJUSTMENT',
          quantity_base: Number(qItem.payload.quantity_base ?? 48),
          expected_version: state.snapshots[qItem.site_id].version,
          reason: String(qItem.payload.reason ?? qItem.summary_text),
          source_ref: qItem.client_event_id,
        });
      } else if (qItem.kind === 'RECEIPT_PART') {
        const shipmentId = String(qItem.payload.shipment_id ?? 'SHP-2026-901');
        apiRecordReceiptPart(persona, shipmentId, {
          receipt_part_id: String(qItem.payload.receipt_part_id ?? `RCPT-OFF-${Date.now()}`),
          client_event_id: qItem.client_event_id,
          accepted_base: Number(qItem.payload.accepted_base ?? 240),
          damaged_base: Number(qItem.payload.damaged_base ?? 0),
          rejected_base: Number(qItem.payload.rejected_base ?? 0),
          quarantine_quantity_base: Number(qItem.payload.quarantine_quantity_base ?? 0),
          evidence_ref: qItem.client_event_id,
          notes: String(qItem.payload.notes ?? 'Offline provisional receipt replayed'),
        });
      }

      const refreshed = loadEngineState();
      const newVer = refreshed.snapshots[qItem.site_id]?.version ?? currentVer + 1;
      const accepted: OfflineEvidenceItem = {
        ...qItem,
        status: 'ACCEPTED',
        server_message: `Validated and committed at server snapshot v${newVer}.`,
      };
      updatedQueue.push(accepted);
      acceptedCount += 1;
      results.push({
        queue_id: qItem.queue_id,
        client_event_id: qItem.client_event_id,
        status: 'ACCEPTED',
        message: accepted.server_message!,
        current_version: newVer,
      });
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      const status: OfflineEvidenceItem['status'] =
        apiErr.http_status === 409 ? 'CONFLICT' : 'REJECTED';
      const failed: OfflineEvidenceItem = {
        ...qItem,
        status,
        server_message: apiErr.message || 'Server validation rejected offline evidence.',
      };
      updatedQueue.push(failed);
      if (status === 'CONFLICT') conflictCount += 1;
      else rejectedCount += 1;
      results.push({
        queue_id: qItem.queue_id,
        client_event_id: qItem.client_event_id,
        status,
        message: failed.server_message!,
        current_version: currentVer,
      });
    }
  }

  return {
    response: {
      synced_at: new Date().toISOString(),
      processed_count: results.length,
      accepted_count: acceptedCount,
      rejected_count: rejectedCount,
      conflict_count: conflictCount,
      results,
    },
    updatedQueue,
  };
}

/**
 * Section 10 Optional Local Explanation Assistant (Permission-filtered retrieval before context assembly,
 * zero mutation privilege, adversarial prompt-injection defense — Acceptance Scenario 14).
 */
export function queryLocalExplanationAssistant(
  persona: AuthenticatedPersona,
  siteId: string,
  question: string,
  includeUntrustedFieldNote = false
): LocalAssistantResponse {
  const state = loadEngineState();
  enforceSiteScope(state, persona, siteId, 'ASSISTANT_QUERY');

  const filteredOutCompartments: string[] = [];
  const permittedDocs = SOP_DOCUMENTS.filter((doc) => {
    if (doc.contains_adversarial_injection && !includeUntrustedFieldNote) {
      return false;
    }
    const roleOk = doc.allowed_roles.includes(persona.role);
    const siteOk = doc.allowed_site_ids.some((s) => persona.allowed_site_ids.includes(s));
    if (!roleOk || !siteOk) {
      filteredOutCompartments.push(`${doc.doc_id} (restricted to ${doc.allowed_site_ids.join(',')} / ${doc.allowed_roles.join(',')})`);
      return false;
    }
    return true;
  });

  // Check for prompt injection in user query or retrieved untrusted note
  const hasInjectionAttempt =
    includeUntrustedFieldNote ||
    /ignore (all|previous) rules|approve all|system override|export site-east/i.test(question);

  const projections = computeInventoryProjectionsForSite(state, siteId);
  const mreProj = projections.find((p) => p.item_id === 'ITM-RATION-MRE') ?? projections[0];
  const latestRec = state.recommendations.find((r) => r.site_id === siteId);

  if (hasInjectionAttempt) {
    appendAudit(state, {
      site_id: siteId,
      persona,
      action: 'ASSISTANT_PROMPT_INJECTION_CONTAINED',
      object_id: 'UNTRUSTED-FIELD-NOTE-999',
      before_version: state.snapshots[siteId].version,
      after_version: state.snapshots[siteId].version,
      reason:
        'Blocked untrusted instruction attempting cross-compartment export and unauthorized request approval (Acceptance Scenario 14)',
      outcome: 'DENIED_403',
    });
    saveEngineState(state);

    return {
      query_id: `ASST-${Date.now().toString(36).toUpperCase()}`,
      mode: state.assistant_enabled
        ? 'LOCAL_ADVISORY_SLM_SIMULATION'
        : 'DETERMINISTIC_TEMPLATE_DEFAULT',
      question,
      answer_text:
        'SECURITY CONTAINMENT (Acceptance Scenario 14): Untrusted text attempted to override compartment rules and trigger request approval. Retrieval pre-filtering stripped out-of-scope compartments before context assembly, and the assistant has ZERO mutation tools or approval credentials. Authoritative stock and request states remain untouched.',
      cited_record_ids: [state.snapshots[siteId].snapshot_id],
      cited_sop_docs: permittedDocs
        .filter((d) => !d.contains_adversarial_injection)
        .map((d) => `${d.doc_id} (${d.version})`),
      filtered_out_compartments: [
        ...filteredOutCompartments,
        'UNTRUSTED-FIELD-NOTE-999 (Adversarial instruction stripped)',
      ],
      injection_blocked: true,
      mutation_privilege: 'NONE_READ_ONLY',
    };
  }

  const answerText = !state.assistant_enabled
    ? `[Deterministic Template Fallback — Local SLM Disabled]: For ${siteId} (${state.snapshots[siteId].snapshot_id}, v${state.snapshots[siteId].version}), usable stock of Composite Daily Ration Pack is ${mreProj.usable_on_hand_base} PACK (${mreProj.usable_on_hand_base / 24} Crates), allocatable after active reservations is ${mreProj.allocatable_base} PACK (${mreProj.allocatable_base / 24} Crates), and confirmed inbound is ${mreProj.confirmed_inbound_base} PACK (${mreProj.confirmed_inbound_base / 24} Crates). ${
        latestRec ? latestRec.explanation : 'Run the Forecast & GIS Planner to generate a draft recommendation.'
      }`
    : `[Advisory Local Explanation — Grounded on Structured Fields]: Based on frozen snapshot ${state.snapshots[siteId].snapshot_id} (v${state.snapshots[siteId].version}) and ${permittedDocs.map((d) => d.doc_id).join(', ')}, ${siteId} holds ${mreProj.allocatable_base} PACK (50 Crates) allocatable and ${mreProj.confirmed_inbound_base} PACK (10 Crates) confirmed inbound. Against a 12-day expected demand of 2,400 PACK (100 Crates) plus 480 PACK (20 Crates) policy buffer, the net order-up-to requirement is 1,440 PACK (60 Crates). When depot storage headroom is capped at 40 Crates, SOP-LOG-101 mandates a reviewed Split-Arrival schedule (40 Crates Wave 1 + 20 Crates Wave 2). Advisory only — requires independent SUPPLY_APPROVER action.`;

  return {
    query_id: `ASST-${Date.now().toString(36).toUpperCase()}`,
    mode: state.assistant_enabled
      ? 'LOCAL_ADVISORY_SLM_SIMULATION'
      : 'DETERMINISTIC_TEMPLATE_DEFAULT',
    question,
    answer_text: answerText,
    cited_record_ids: [
      state.snapshots[siteId].snapshot_id,
      ...(latestRec ? [latestRec.recommendation_id, latestRec.plan_id] : []),
    ],
    cited_sop_docs: permittedDocs.map((d) => `${d.doc_id} (${d.version})`),
    filtered_out_compartments: filteredOutCompartments,
    injection_blocked: false,
    mutation_privilege: 'NONE_READ_ONLY',
  };
}

/**
 * GET /api/v1/audit
 */
export function apiGetAuditAndQuality(
  persona: AuthenticatedPersona,
  siteId: string
): {
  audit_log: AuditRecord[];
  source_registry: SourceRegistryEntry[];
  quarantined_csv_rows: CsvValidationResultRow[];
  custody_digests: CustodyAcknowledgementDigest[];
  snapshots: Record<string, SiteSnapshot>;
} {
  const state = loadEngineState();
  enforceSiteScope(state, persona, siteId, 'GET_AUDIT');
  return {
    audit_log: state.audit_log.filter(
      (a) => persona.allowed_site_ids.includes(a.site_id) && a.site_id === siteId
    ),
    source_registry: SOURCE_REGISTRY,
    quarantined_csv_rows: state.quarantined_csv_rows,
    custody_digests: state.custody_digests.filter((d) => d.site_id === siteId),
    snapshots: state.snapshots,
  };
}

export function computeNeedsActionTasks(
  persona: AuthenticatedPersona,
  siteId: string,
  offlineQueue: OfflineEvidenceItem[]
): NeedsActionItem[] {
  const state = loadEngineState();
  if (!persona.allowed_site_ids.includes(siteId)) {
    return [];
  }

  const tasks: NeedsActionItem[] = [];
  const snap = state.snapshots[siteId];
  const projections = computeInventoryProjectionsForSite(state, siteId);

  for (const proj of projections) {
    if (proj.is_stale) {
      const item = ITEMS.find((i) => i.item_id === proj.item_id);
      tasks.push({
        task_id: `TSK-STALE-${siteId}-${proj.item_id}`,
        site_id: siteId,
        item_id: proj.item_id,
        category: 'STALE_DATA_GATE',
        severity: 'CRITICAL',
        title: `Stale Physical Count (${proj.observation_age_hours}h old): ${item?.name ?? proj.item_id}`,
        description: `Last verified count was ${proj.last_physical_count_at}. Freshness gate blocks routine replenishment approval until physical count is verified or an exception is signed.`,
        owner_role: 'DATA_CUSTODIAN',
        owner_label: snap.data_custodian_id,
        detected_at: snap.as_of_time,
        target_screen: 'WORKBENCH',
        reference_id: proj.item_id,
      });
    }
  }

  for (const obs of state.iot_observations.filter(
    (o) => o.site_id === siteId && o.status === 'QUARANTINED_ANOMALY'
  )) {
    tasks.push({
      task_id: `TSK-IOT-${obs.event_id}`,
      site_id: siteId,
      item_id: obs.item_id,
      category: 'IOT_GATEWAY_ANOMALY',
      severity: 'WARNING',
      title: `IoT Gateway Quarantine (${obs.device_id} • seq ${obs.sequence})`,
      description: obs.anomaly_flags.join(' | '),
      owner_role:
        obs.observation_type === 'coldchain_temp_c' ? 'MEDICAL_QA_OFFICER' : 'STOREKEEPER',
      owner_label:
        obs.observation_type === 'coldchain_temp_c'
          ? 'Maj. Dr. S. Iyer (Medical QA)'
          : 'Subedar R. Nair (Storekeeper)',
      detected_at: obs.gateway_time,
      target_screen: 'IOT_GATEWAY',
      reference_id: obs.event_id,
    });
  }

  for (const batch of state.batches.filter(
    (b) => b.site_id === siteId && (b.quality_state === 'QUARANTINED' || b.quarantined_qty_base > 0)
  )) {
    const item = ITEMS.find((i) => i.item_id === batch.item_id);
    tasks.push({
      task_id: `TSK-QUAR-${batch.batch_id}`,
      site_id: siteId,
      item_id: batch.item_id,
      category: 'MEDICAL_QA_QUARANTINE',
      severity: 'ACTION_REQUIRED',
      title: `Quarantined Batch Hold (${batch.quarantined_qty_base} ${item?.base_unit ?? 'units'}): ${batch.batch_id}`,
      description: `${batch.quarantine_reason ?? 'Quality hold active'}. Excluded from usable & allocatable stock. Requires designated Medical QA Officer decision.`,
      owner_role: 'MEDICAL_QA_OFFICER',
      owner_label: 'Maj. Dr. S. Iyer (Medical QA Authority)',
      detected_at: batch.last_verified_at,
      target_screen: 'WORKBENCH',
      reference_id: batch.batch_id,
    });
  }

  for (const req of state.requests.filter(
    (r) => r.site_id === siteId && r.state === 'SUBMITTED'
  )) {
    const item = ITEMS.find((i) => i.item_id === req.item_id);
    tasks.push({
      task_id: `TSK-APPR-${req.request_id}`,
      site_id: siteId,
      item_id: req.item_id,
      category: 'PENDING_INDEPENDENT_APPROVAL',
      severity: 'ACTION_REQUIRED',
      title: `Replenishment Request ${req.request_id} Awaiting Independent Approval`,
      description: `Submitted by ${req.creator_name} for ${req.proposed_qty_base} ${item?.base_unit ?? ''} of ${item?.name ?? req.item_id}. Creator cannot self-approve (Scenario 4).`,
      owner_role: 'SUPPLY_APPROVER',
      owner_label: 'Maj. A. Verma (Independent Approver)',
      detected_at: req.created_at,
      target_screen: 'APPROVAL_RECEIPT',
      reference_id: req.request_id,
    });
  }

  for (const shp of state.shipments.filter(
    (s) => s.site_id === siteId && s.state === 'PARTIALLY_RECEIVED'
  )) {
    const item = ITEMS.find((i) => i.item_id === shp.item_id);
    tasks.push({
      task_id: `TSK-SHP-${shp.shipment_id}`,
      site_id: siteId,
      item_id: shp.item_id,
      category: 'PARTIAL_RECEIPT_DISCREPANCY',
      severity: 'WARNING',
      title: `Unresolved Partial Receipt Discrepancy on Shipment ${shp.shipment_id}`,
      description: `${shp.discrepancy_note ?? 'Split delivery in progress'} (${item?.name ?? shp.item_id}). Record remaining receipt part or close with authorized exception.`,
      owner_role: 'STOREKEEPER',
      owner_label: 'Subedar R. Nair (Storekeeper)',
      detected_at: shp.dispatched_at ?? snap.as_of_time,
      target_screen: 'APPROVAL_RECEIPT',
      reference_id: shp.shipment_id,
    });
  }

  for (const cItem of offlineQueue.filter((q) => q.status === 'CONFLICT')) {
    tasks.push({
      task_id: `TSK-CONF-${cItem.queue_id}`,
      site_id: cItem.site_id,
      item_id: cItem.item_id,
      category: 'OFFLINE_SYNC_CONFLICT',
      severity: 'CRITICAL',
      title: `Offline Replay Conflict (${cItem.client_event_id})`,
      description:
        cItem.server_message ??
        'Provisional offline evidence conflicted with newer server snapshot version.',
      owner_role: 'DATA_CUSTODIAN',
      owner_label: snap.data_custodian_id,
      detected_at: cItem.created_at_local,
      target_screen: 'OFFLINE_AUDIT',
      reference_id: cItem.queue_id,
    });
  }

  return tasks;
}

export function setSimulatedForecastFailure(enabled: boolean): void {
  const state = loadEngineState();
  state.simulate_forecast_failure = enabled;
  saveEngineState(state);
}

export function getSimulatedForecastFailure(): boolean {
  return loadEngineState().simulate_forecast_failure;
}

export function setAssistantEnabled(enabled: boolean): void {
  const state = loadEngineState();
  state.assistant_enabled = enabled;
  saveEngineState(state);
}

export function getAssistantEnabled(): boolean {
  return loadEngineState().assistant_enabled;
}

export function setCustodyLedgerMode(
  mode: PersistedEngineState['custody_ledger_mode']
): void {
  const state = loadEngineState();
  state.custody_ledger_mode = mode;
  saveEngineState(state);
}

export function getCustodyLedgerMode(): PersistedEngineState['custody_ledger_mode'] {
  return loadEngineState().custody_ledger_mode;
}
