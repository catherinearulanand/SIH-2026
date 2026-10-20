/**
 * Setu Supply (SIH26251) — Final Proposal Typed API Client & Offline / IoT Store-and-Forward Interceptor
 */

import {
  ApiErrorEnvelope,
  AuthenticatedPersona,
  CsvImportCandidateRow,
  ForecastModelVersion,
  ForecastRun,
  GISPlan,
  ImportValidationPreview,
  InventoryEvent,
  IoTObservation,
  IoTObservationType,
  OfflineEvidenceItem,
  Recommendation,
  ReplenishmentRequest,
  ScenarioAssumptions,
  ShipmentLine,
} from '../contracts/api';
import {
  cacheSiteSnapshot,
  enqueueOfflineEvidence,
  listOfflineEvidenceQueue,
  updateOfflineEvidenceItems,
} from './indexedDbQueue';
import {
  apiApproveRequest,
  apiCommitCsvImport,
  apiCreateRecommendation,
  apiCreateRequest,
  apiGetAuditAndQuality,
  apiGetInventory,
  apiIngestIoTObservation,
  apiPostInventoryEvent,
  apiPromoteObservationToLedgerEvent,
  apiRecordReceiptPart,
  apiRecordShipmentDispatch,
  apiReserveRequestStock,
  apiRunForecast,
  apiRunGisPlanning,
  apiSyncOfflineQueue,
  apiValidateCsvImport,
  loadEngineState,
  queryLocalExplanationAssistant,
} from './mockContractEngine';

export type NetworkConnectivityMode =
  | 'ONLINE'
  | 'OFFLINE_CACHED_AUTH'
  | 'OFFLINE_AUTHORITY_EXPIRED';

export class SetuApiClient {
  private networkMode: NetworkConnectivityMode = 'ONLINE';
  private useLiveBackendHttp = false;

  public setNetworkMode(mode: NetworkConnectivityMode): void {
    this.networkMode = mode;
  }

  public getNetworkMode(): NetworkConnectivityMode {
    return this.networkMode;
  }

  public setUseLiveBackendHttp(enabled: boolean): void {
    this.useLiveBackendHttp = enabled;
  }

  public getUseLiveBackendHttp(): boolean {
    return this.useLiveBackendHttp;
  }

  private async tryLiveFetch<T>(
    path: string,
    options: RequestInit,
    persona: AuthenticatedPersona,
    fallbackFn: () => T | Promise<T>
  ): Promise<T> {
    if (!this.useLiveBackendHttp) {
      return await fallbackFn();
    }
    try {
      const res = await fetch(`/api/v1${path}`, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          'X-Actor-Id': persona.user_id,
          'X-Actor-Role': persona.role,
          'X-Allowed-Sites': persona.allowed_site_ids.join(','),
          ...(options.headers || {}),
        },
      });
      if (!res.ok) {
        const errBody = (await res.json()) as ApiErrorEnvelope;
        throw errBody;
      }
      return (await res.json()) as T;
    } catch (err) {
      if ((err as ApiErrorEnvelope)?.code) {
        throw err;
      }
      return await fallbackFn();
    }
  }

  public async getInventory(persona: AuthenticatedPersona, siteId: string) {
    const result = await this.tryLiveFetch(
      `/inventory?site_id=${encodeURIComponent(siteId)}`,
      { method: 'GET' },
      persona,
      () => apiGetInventory(persona, siteId)
    );
    if (this.networkMode === 'ONLINE' && result.snapshot) {
      await cacheSiteSnapshot(result.snapshot);
    }
    return result;
  }

  /**
   * POST /api/v1/observations
   * When offline, buffers the IoT observation in the bounded store-and-forward queue (Section 8 Rule 6).
   */
  public async postIoTObservation(
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
  ): Promise<{
    observation?: IoTObservation;
    queued_offline?: OfflineEvidenceItem;
    duplicate_ignored?: boolean;
    sequence_gap_detected?: boolean;
  }> {
    if (this.networkMode !== 'ONLINE') {
      const state = loadEngineState();
      const expectedVer = state.snapshots[input.site_id]?.version ?? 1;
      const queueItem: OfflineEvidenceItem = {
        queue_id: `Q-IOT-${Date.now().toString(36).toUpperCase()}`,
        client_event_id: input.event_id,
        kind:
          this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED'
            ? 'SUPERVISED_BLANK_EVIDENCE'
            : 'IOT_GATEWAY_OBSERVATION',
        site_id: input.site_id,
        item_id: input.item_id,
        created_by: persona.user_id,
        created_by_role: persona.role,
        created_at_local: new Date().toISOString(),
        expected_version: expectedVer,
        payload: { ...input },
        summary_text: `Store-and-Forward IoT Observation (${input.device_id} • ${input.boot_session} • seq=${input.sequence}): ${input.observation_type} = ${input.value} ${input.unit} on ${input.batch_id}`,
        status: 'PENDING',
        authority_expired_capture: this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED',
      };
      await enqueueOfflineEvidence(queueItem);
      return { queued_offline: queueItem };
    }

    return this.tryLiveFetch(
      '/observations',
      {
        method: 'POST',
        body: JSON.stringify(input),
      },
      persona,
      () => apiIngestIoTObservation(persona, input)
    );
  }

  public async promoteObservationToLedger(
    persona: AuthenticatedPersona,
    observationEventId: string,
    eventType: 'RECEIPT' | 'ISSUE' | 'COMPENSATING_ADJUSTMENT',
    reason: string
  ): Promise<InventoryEvent> {
    if (this.networkMode !== 'ONLINE') {
      const err: ApiErrorEnvelope = {
        code: 'OFFLINE_PROMOTION_BLOCKED',
        message:
          'Promoting an IoT observation to an authoritative stock mutation requires an online server transaction (Section 8 Rule 7).',
        field_errors: {},
        correlation_id: `CORR-OFF-${Date.now()}`,
        current_version: 0,
        http_status: 409,
      };
      throw err;
    }
    return apiPromoteObservationToLedgerEvent(
      persona,
      observationEventId,
      eventType,
      reason
    );
  }

  public async validateCsvImport(
    persona: AuthenticatedPersona,
    siteId: string,
    candidateRows?: CsvImportCandidateRow[]
  ): Promise<ImportValidationPreview> {
    return this.tryLiveFetch(
      '/imports/validate',
      {
        method: 'POST',
        body: JSON.stringify({ site_id: siteId, rows: candidateRows }),
      },
      persona,
      () => apiValidateCsvImport(persona, siteId, candidateRows)
    );
  }

  public async commitCsvImport(persona: AuthenticatedPersona, validationId: string) {
    if (this.networkMode !== 'ONLINE') {
      const err: ApiErrorEnvelope = {
        code: 'OFFLINE_BULK_COMMIT_BLOCKED',
        message:
          'Bulk CSV ledger commit requires an active server connection. While disconnected, use the Provisional Evidence Queue.',
        field_errors: {},
        correlation_id: `CORR-OFF-${Date.now()}`,
        current_version: 0,
        http_status: 409,
      };
      throw err;
    }
    return this.tryLiveFetch(
      '/imports/commit',
      {
        method: 'POST',
        body: JSON.stringify({ validation_id: validationId }),
      },
      persona,
      () => apiCommitCsvImport(persona, validationId)
    );
  }

  public async postInventoryEvent(
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
    }
  ): Promise<{
    event?: InventoryEvent;
    queued_offline?: OfflineEvidenceItem;
    idempotent_replay?: boolean;
    current_version: number;
  }> {
    if (this.networkMode !== 'ONLINE') {
      if (input.type === 'QA_RELEASE') {
        const err: ApiErrorEnvelope = {
          code: 'OFFLINE_QA_RELEASE_PROHIBITED',
          message:
            'Medical Quarantine QA release cannot be committed offline. Requires online Medical QA authority verification.',
          field_errors: {},
          correlation_id: `CORR-OFF-${Date.now()}`,
          current_version: input.expected_version,
          http_status: 403,
        };
        throw err;
      }

      const queueItem: OfflineEvidenceItem = {
        queue_id: `Q-${Date.now().toString(36).toUpperCase()}`,
        client_event_id: input.client_event_id,
        kind:
          this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED'
            ? 'SUPERVISED_BLANK_EVIDENCE'
            : 'PHYSICAL_COUNT_ADJUSTMENT',
        site_id: input.site_id,
        item_id: input.item_id,
        created_by: persona.user_id,
        created_by_role: persona.role,
        created_at_local: new Date().toISOString(),
        expected_version: input.expected_version,
        payload: { ...input },
        summary_text: `Provisional ${input.type} (${input.quantity_base >= 0 ? '+' : ''}${input.quantity_base} base units on ${input.batch_id}): ${input.reason}`,
        status: 'PENDING',
        authority_expired_capture: this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED',
      };
      await enqueueOfflineEvidence(queueItem);
      return {
        queued_offline: queueItem,
        current_version: input.expected_version,
      };
    }

    return this.tryLiveFetch(
      '/inventory-events',
      {
        method: 'POST',
        body: JSON.stringify(input),
      },
      persona,
      () => apiPostInventoryEvent(persona, input)
    );
  }

  public async runForecast(
    persona: AuthenticatedPersona,
    params: {
      site_id: string;
      item_id: string;
      horizon_days?: number;
      preferred_model?: ForecastModelVersion;
      scenario?: ScenarioAssumptions;
    }
  ): Promise<ForecastRun> {
    return this.tryLiveFetch(
      '/forecast-runs',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiRunForecast(persona, params)
    );
  }

  /**
   * POST /api/v1/planning-runs
   */
  public async runGisPlanning(
    persona: AuthenticatedPersona,
    params: {
      site_id: string;
      item_id: string;
      required_packs: number;
      scenario: ScenarioAssumptions;
    }
  ): Promise<GISPlan> {
    return this.tryLiveFetch(
      '/planning-runs',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiRunGisPlanning(persona, params)
    );
  }

  public async createRecommendation(
    persona: AuthenticatedPersona,
    params: {
      site_id: string;
      item_id: string;
      scenario: ScenarioAssumptions;
      preferred_model?: ForecastModelVersion;
    }
  ): Promise<{
    recommendation: Recommendation;
    forecast_run: ForecastRun;
    gis_plan: GISPlan;
  }> {
    return this.tryLiveFetch(
      '/recommendations',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiCreateRecommendation(persona, params)
    );
  }

  public async createRequest(
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
    }
  ): Promise<{
    request?: ReplenishmentRequest;
    queued_offline?: OfflineEvidenceItem;
  }> {
    if (this.networkMode !== 'ONLINE') {
      const state = loadEngineState();
      const expectedVer = state.snapshots[params.site_id]?.version ?? 1;
      const queueItem: OfflineEvidenceItem = {
        queue_id: `Q-REQ-${Date.now().toString(36).toUpperCase()}`,
        client_event_id: params.client_event_id,
        kind:
          this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED'
            ? 'SUPERVISED_BLANK_EVIDENCE'
            : 'DRAFT_REQUEST',
        site_id: params.site_id,
        item_id: params.item_id,
        created_by: persona.user_id,
        created_by_role: persona.role,
        created_at_local: new Date().toISOString(),
        expected_version: expectedVer,
        payload: { ...params },
        summary_text: `Provisional Replenishment Request for ${params.proposed_qty_base} base units of ${params.item_id} (linked to ${params.source_recommendation_id})`,
        status: 'PENDING',
        authority_expired_capture: this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED',
      };
      await enqueueOfflineEvidence(queueItem);
      return { queued_offline: queueItem };
    }

    const request = await this.tryLiveFetch(
      '/requests',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiCreateRequest(persona, params)
    );
    return { request };
  }

  public async approveRequest(
    persona: AuthenticatedPersona,
    requestId: string,
    params: {
      decision: 'APPROVED' | 'REJECTED' | 'APPROVED_WITH_CHANGE';
      approved_qty_base: number;
      reason: string;
      acknowledge_stale_gate?: boolean;
    }
  ) {
    if (this.networkMode !== 'ONLINE') {
      const err: ApiErrorEnvelope = {
        code: 'OFFLINE_APPROVAL_PROHIBITED',
        message:
          'Offline approval is prohibited (Section 11 & 12): Independent approval requires online server revalidation against current stock, version, and policy.',
        field_errors: {},
        correlation_id: `CORR-OFF-${Date.now()}`,
        current_version: 0,
        http_status: 409,
      };
      throw err;
    }
    return this.tryLiveFetch(
      `/requests/${encodeURIComponent(requestId)}/approve`,
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiApproveRequest(persona, requestId, params)
    );
  }

  public async reserveRequestStock(
    persona: AuthenticatedPersona,
    requestId: string,
    params: {
      reserve_qty_base: number;
      expected_version: number;
    }
  ): Promise<ReplenishmentRequest> {
    if (this.networkMode !== 'ONLINE') {
      const err: ApiErrorEnvelope = {
        code: 'OFFLINE_RESERVATION_PROHIBITED',
        message:
          'Offline shared-stock reservation is strictly prohibited (Section 2 & 12): Disconnected users cannot promise or reserve cached stock locally.',
        field_errors: {},
        correlation_id: `CORR-OFF-${Date.now()}`,
        current_version: params.expected_version,
        http_status: 409,
      };
      throw err;
    }
    return this.tryLiveFetch(
      `/requests/${encodeURIComponent(requestId)}/reserve`,
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiReserveRequestStock(persona, requestId, params)
    );
  }

  public async recordShipmentDispatch(
    persona: AuthenticatedPersona,
    shipmentId: string,
    params: {
      dispatched_quantity_base: number;
      expected_arrival_date: string;
      notes: string;
    }
  ): Promise<ShipmentLine> {
    return this.tryLiveFetch(
      `/shipments/${encodeURIComponent(shipmentId)}/dispatch-record`,
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiRecordShipmentDispatch(persona, shipmentId, params)
    );
  }

  public async recordReceiptPart(
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
  ) {
    if (this.networkMode !== 'ONLINE') {
      const state = loadEngineState();
      const shp = state.shipments.find((s) => s.shipment_id === shipmentId);
      const siteId = shp?.site_id ?? persona.default_site_id;
      const itemId = shp?.item_id ?? 'ITM-RATION-MRE';
      const expectedVer = state.snapshots[siteId]?.version ?? 1;

      const queueItem: OfflineEvidenceItem = {
        queue_id: `Q-RCPT-${Date.now().toString(36).toUpperCase()}`,
        client_event_id: params.client_event_id,
        kind:
          this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED'
            ? 'SUPERVISED_BLANK_EVIDENCE'
            : 'RECEIPT_PART',
        site_id: siteId,
        item_id: itemId,
        created_by: persona.user_id,
        created_by_role: persona.role,
        created_at_local: new Date().toISOString(),
        expected_version: expectedVer,
        payload: {
          shipment_id: shipmentId,
          ...params,
        },
        summary_text: `Provisional Receipt Part ${params.receipt_part_id} on ${shipmentId}: Accepted=${params.accepted_base}, Damaged=${params.damaged_base}, Rejected=${params.rejected_base}, Quarantine=${params.quarantine_quantity_base}`,
        status: 'PENDING',
        authority_expired_capture: this.networkMode === 'OFFLINE_AUTHORITY_EXPIRED',
      };
      await enqueueOfflineEvidence(queueItem);
      return {
        queued_offline: queueItem,
        idempotent_replay: false,
      };
    }

    return this.tryLiveFetch(
      `/shipments/${encodeURIComponent(shipmentId)}/receipt-parts`,
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      persona,
      () => apiRecordReceiptPart(persona, shipmentId, params)
    );
  }

  public async syncOfflineEvidence(
    persona: AuthenticatedPersona,
    forceAcceptConflicts = false
  ) {
    if (this.networkMode !== 'ONLINE') {
      const err: ApiErrorEnvelope = {
        code: 'CANNOT_SYNC_WHILE_OFFLINE',
        message: 'Switch connectivity mode to ONLINE before replaying provisional offline evidence.',
        field_errors: {},
        correlation_id: `CORR-OFF-${Date.now()}`,
        current_version: 0,
        http_status: 409,
      };
      throw err;
    }

    const currentQueue = await listOfflineEvidenceQueue();
    const { response, updatedQueue } = apiSyncOfflineQueue(
      persona,
      currentQueue,
      forceAcceptConflicts
    );
    await updateOfflineEvidenceItems(updatedQueue);
    return { response, updatedQueue };
  }

  public async getAuditAndQuality(persona: AuthenticatedPersona, siteId: string) {
    return this.tryLiveFetch(
      `/audit?site_id=${encodeURIComponent(siteId)}`,
      { method: 'GET' },
      persona,
      () => apiGetAuditAndQuality(persona, siteId)
    );
  }

  public async askLocalAssistant(
    persona: AuthenticatedPersona,
    siteId: string,
    question: string,
    includeUntrustedFieldNote = false
  ) {
    return queryLocalExplanationAssistant(
      persona,
      siteId,
      question,
      includeUntrustedFieldNote
    );
  }
}

export const setuApiClient = new SetuApiClient();
