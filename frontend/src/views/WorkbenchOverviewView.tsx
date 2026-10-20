/**
 * Setu Supply (SIH26251) — Tab 1: Operator Workbench, Stock Authority, Freshness & CSV Import
 */

import React, { useState } from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  Database,
  FileSpreadsheet,
  Layers,
  ShieldAlert,
  ShieldCheck,
  Upload,
} from 'lucide-react';
import {
  ApiErrorEnvelope,
  AuthenticatedPersona,
  Batch,
  ImportValidationPreview,
  InventoryEvent,
  InventoryProjection,
  Item,
  NeedsActionItem,
  Site,
  SiteSnapshot,
} from '../contracts/api';
import {
  FreshnessBadge,
  QuantityDisplay,
  QualityStateBadge,
  TimestampTrioBar,
} from '../components/StatusBadges';
import { ActiveTabId } from '../components/DemoWalkthroughBar';
import { setuApiClient } from '../services/apiClient';

interface WorkbenchOverviewViewProps {
  persona: AuthenticatedPersona;
  site: Site;
  snapshot: SiteSnapshot;
  items: Item[];
  projections: InventoryProjection[];
  batches: Batch[];
  events: InventoryEvent[];
  needsAction: NeedsActionItem[];
  onNavigateTab: (tab: ActiveTabId, itemId?: string) => void;
  onRefreshState: () => void;
  onNotify: (msg: string, tone: 'success' | 'error' | 'info') => void;
}

export const WorkbenchOverviewView: React.FC<WorkbenchOverviewViewProps> = ({
  persona,
  site,
  snapshot,
  items,
  projections,
  batches,
  events,
  needsAction,
  onNavigateTab,
  onRefreshState,
  onNotify,
}) => {
  const [csvPreview, setCsvPreview] = useState<ImportValidationPreview | null>(null);
  const [adjustBatchId, setAdjustBatchId] = useState<string>(batches[0]?.batch_id ?? '');
  const [adjustDeltaBase, setAdjustDeltaBase] = useState<number>(48);
  const [adjustReason, setAdjustReason] = useState<string>(
    'Verified physical stock count reconciliation sheet #2026-10-20'
  );
  const [adjustClientKey, setAdjustClientKey] = useState<string>(
    `CEV-CNT-${Date.now().toString(36).toUpperCase()}`
  );
  const [qaReleaseReason, setQaReleaseReason] = useState<string>(
    'Cold-chain strip verified within cumulative stability budget; healthy units cleared for issue'
  );

  const itemMap = new Map(items.map((i) => [i.item_id, i]));

  const handleRunCsvValidate = async () => {
    try {
      const preview = await setuApiClient.validateCsvImport(persona, site.site_id);
      setCsvPreview(preview);
      onRefreshState();
      onNotify(
        `CSV Preview ${preview.validation_id}: ${preview.valid_count} valid rows ready, ${preview.quarantined_count} invalid rows quarantined for review.`,
        'info'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'CSV validation failed', 'error');
    }
  };

  const handleCommitCsv = async () => {
    if (!csvPreview) return;
    try {
      const res = await setuApiClient.commitCsvImport(persona, csvPreview.validation_id);
      setCsvPreview(res.preview);
      onRefreshState();
      onNotify(
        `Committed ${res.committed_events.length} valid events to Ledger v${res.new_snapshot_version}. Quarantined rows preserved in Audit tab.`,
        'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'CSV commit failed', 'error');
    }
  };

  const handleCompensatingAdjustment = async (e: React.FormEvent) => {
    e.preventDefault();
    const targetBatch = batches.find((b) => b.batch_id === adjustBatchId) ?? batches[0];
    if (!targetBatch) return;
    try {
      const res = await setuApiClient.postInventoryEvent(persona, {
        client_event_id: adjustClientKey,
        site_id: site.site_id,
        item_id: targetBatch.item_id,
        batch_id: targetBatch.batch_id,
        type: 'COMPENSATING_ADJUSTMENT',
        quantity_base: Number(adjustDeltaBase),
        expected_version: snapshot.version,
        reason: adjustReason,
        source_ref: `COUNT-ADJ-${adjustBatchId}`,
      });
      onRefreshState();
      if (res.queued_offline) {
        onNotify(
          `Offline Mode: Queued provisional count adjustment (${res.queued_offline.client_event_id}) in IndexedDB.`,
          'info'
        );
      } else if (res.idempotent_replay) {
        onNotify(
          `Idempotent Replay (Scenario 1): Key '${adjustClientKey}' already committed. Stock was NOT modified a second time.`,
          'info'
        );
      } else {
        onNotify(
          `Recorded compensating adjustment ${res.event?.event_id} on ${targetBatch.batch_id} (Ledger v${res.current_version}).`,
          'success'
        );
        setAdjustClientKey(`CEV-CNT-${Date.now().toString(36).toUpperCase()}`);
      }
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Failed to record count adjustment', 'error');
    }
  };

  const handleQaReleaseBatch = async (batch: Batch) => {
    try {
      const res = await setuApiClient.postInventoryEvent(persona, {
        client_event_id: `CEV-QAREL-${batch.batch_id}-${Date.now().toString(36)}`,
        site_id: site.site_id,
        item_id: batch.item_id,
        batch_id: batch.batch_id,
        type: 'QA_RELEASE',
        quantity_base: batch.quarantined_qty_base,
        expected_version: snapshot.version,
        reason: qaReleaseReason,
        source_ref: `MED-QA-CERT-${batch.batch_id}`,
      });
      onRefreshState();
      onNotify(
        `Medical QA Release committed (${res.event?.event_id}): Healthy units in ${batch.batch_id} restored to usable stock.`,
        'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Medical QA Release denied', 'error');
    }
  };

  return (
    <div className="view-stack">
      {/* Depot Digital Representation & Frozen Planning Snapshot Header */}
      <section className="panel panel-highlight">
        <div className="panel-header-row">
          <div>
            <div className="eyebrow">
              <Database size={14} /> DEPOT DIGITAL REPRESENTATION &amp; VERSIONED SNAPSHOT BOUNDARY
            </div>
            <h2>
              {site.display_alias} <span className="mono-badge">{snapshot.snapshot_id} (v{snapshot.version})</span>
            </h2>
          </div>
          <div className="snapshot-meta-badges">
            <span className="meta-chip">
              Graph: <code>{snapshot.graph_version}</code>
            </span>
            <span className="meta-chip">
              Policy: <code>{snapshot.policy_version}</code>
            </span>
            <span className="meta-chip">
              Custodian: <strong>{site.data_custodian_id}</strong>
            </span>
            <span className="meta-chip">
              Fictional Grid: <code>{site.fictional_grid_ref}</code>
            </span>
          </div>
        </div>

        <TimestampTrioBar
          observedAt={snapshot.as_of_time}
          syncedAt={snapshot.synced_at}
          lastPhysicalCountAt={snapshot.last_physical_count_at}
          observationAgeHours={
            projections.reduce((max, p) => Math.max(max, p.observation_age_hours), 6)
          }
          isStale={snapshot.freshness_status === 'STALE_GATE_ACTIVE'}
        />
      </section>

      {/* Assigned Needs-Action Exceptions */}
      <section className="panel">
        <div className="panel-header-row">
          <div>
            <h3>
              <AlertTriangle size={17} /> Assigned Exceptions &amp; Operational Tasks ({needsAction.length})
            </h3>
            <p className="panel-subtext">
              Every exception carries an explicit severity, designated role owner, and direct resolution path.
            </p>
          </div>
        </div>

        <div className="exceptions-grid">
          {needsAction.map((tsk) => (
            <div
              key={tsk.task_id}
              className={`exception-card exception-${tsk.severity.toLowerCase()}`}
            >
              <div className="exception-top">
                <span className={`badge ${tsk.severity === 'CRITICAL' ? 'badge-danger' : 'badge-warning'}`}>
                  {tsk.severity === 'CRITICAL' ? <AlertOctagon size={13} /> : <AlertTriangle size={13} />}
                  <span>{tsk.severity}</span>
                </span>
                <span className="owner-tag">Owner: {tsk.owner_label}</span>
              </div>
              <h4>{tsk.title}</h4>
              <p>{tsk.description}</p>
              <div className="exception-footer">
                <code>Ref: {tsk.reference_id}</code>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => onNavigateTab(tsk.target_screen, tsk.item_id)}
                >
                  <span>Resolve in {tsk.target_screen.replace('_', ' ')}</span>
                  <ArrowRight size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Authoritative Inventory Accounting Matrix */}
      <section className="panel">
        <div className="panel-header-row">
          <div>
            <h3>
              <Layers size={17} /> Authoritative Inventory Accounting Matrix (Section 11 Invariants)
            </h3>
            <p className="panel-subtext">
              <strong>Quality-Unavailable</strong> is the union of Expired, Damaged, and Quarantined stock (never double-subtracted).{' '}
              <strong>Usable</strong> = Physical − Quality-Unavailable.{' '}
              <strong>Allocatable</strong> = Usable − Active Reservations. Confirmed Inbound and Open Requests are tracked separately.
            </p>
          </div>
        </div>

        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Item &amp; Pack Rule</th>
                <th>Freshness &amp; Last Count</th>
                <th>Physical On-Hand (Gross)</th>
                <th>Quality-Unavailable (Union: Exp / Dmg / Quar)</th>
                <th>Usable On-Hand</th>
                <th>Active Reserved</th>
                <th>Allocatable Stock (Authority)</th>
                <th>Confirmed Inbound (Separate)</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {projections.map((proj) => {
                const item = itemMap.get(proj.item_id);
                return (
                  <tr key={proj.item_id} className={proj.is_stale ? 'row-stale' : ''}>
                    <td>
                      <div className="cell-title">{item?.name ?? proj.item_id}</div>
                      <div className="cell-sub">
                        <code>{proj.item_id}</code> • 1 {item?.pack_name} = {item?.pack_size_base}{' '}
                        {item?.base_unit} ({item?.pack_conversion_version})
                      </div>
                    </td>
                    <td>
                      <FreshnessBadge
                        status={proj.is_stale ? 'STALE_GATE_ACTIVE' : proj.observation_age_hours > 24 ? 'AGING' : 'FRESH'}
                        ageHours={proj.observation_age_hours}
                      />
                      <div className="cell-sub">
                        Count: {proj.last_physical_count_at.slice(0, 16).replace('T', ' ')}
                      </div>
                    </td>
                    <td>
                      <QuantityDisplay qtyBase={proj.physical_on_hand_base} item={item} />
                    </td>
                    <td>
                      <QuantityDisplay
                        qtyBase={proj.quality_unavailable_base}
                        item={item}
                        highlight={proj.quality_unavailable_base > 0 ? 'danger' : 'neutral'}
                      />
                      {proj.quality_unavailable_base > 0 && (
                        <div className="cell-sub">
                          Exp: {proj.expired_qty_base} | Dmg: {proj.damaged_qty_base} | Quar:{' '}
                          {proj.quarantined_qty_base} {item?.base_unit}
                        </div>
                      )}
                    </td>
                    <td>
                      <QuantityDisplay
                        qtyBase={proj.usable_on_hand_base}
                        item={item}
                        highlight="usable"
                      />
                    </td>
                    <td>
                      <QuantityDisplay
                        qtyBase={proj.active_reserved_base}
                        item={item}
                        highlight={proj.active_reserved_base > 0 ? 'warning' : 'neutral'}
                      />
                    </td>
                    <td>
                      <QuantityDisplay
                        qtyBase={proj.allocatable_base}
                        item={item}
                        highlight="usable"
                      />
                      {proj.expiring_within_horizon_base > 0 && (
                        <div className="cell-sub text-warn">
                          ⚠ {proj.expiring_within_horizon_base} {item?.base_unit} expires within horizon
                        </div>
                      )}
                    </td>
                    <td>
                      <QuantityDisplay qtyBase={proj.confirmed_inbound_base} item={item} />
                      <div className="cell-sub">
                        {proj.inbound_arrival_date
                          ? `ETA ${proj.inbound_arrival_date} (${proj.inbound_confirmation_status})`
                          : 'No active inbound'}
                      </div>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={() => onNavigateTab('FORECAST_GIS', proj.item_id)}
                      >
                        Plan &amp; Forecast
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Two-Column Lower Row: Batch Quality & Medical QA + CSV Import / Physical Count */}
      <div className="two-col-grid">
        {/* Batch Ledger & Medical QA Release */}
        <section className="panel">
          <div className="panel-header-row">
            <div>
              <h3>
                <ShieldCheck size={17} /> Batch-Level Quality, Expiry &amp; Medical QA Release
              </h3>
              <p className="panel-subtext">
                Expired and Quarantined batches are automatically excluded from allocation. Releasing Medical Quarantine requires{' '}
                <code>MEDICAL_QA_OFFICER</code> authority (Acceptance Scenario 5).
              </p>
            </div>
          </div>

          <div className="form-group" style={{ marginBottom: '0.75rem' }}>
            <label className="form-label">Medical QA Inspection Release / Hold Note:</label>
            <input
              type="text"
              className="form-input"
              value={qaReleaseReason}
              onChange={(e) => setQaReleaseReason(e.target.value)}
            />
          </div>

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Batch ID &amp; Item</th>
                  <th>Expiry Date</th>
                  <th>Quality State</th>
                  <th>Physical / Damaged / Quarantined</th>
                  <th>QA Action (Scenario 5)</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => {
                  const item = itemMap.get(b.item_id);
                  return (
                    <tr key={b.batch_id}>
                      <td>
                        <strong>{b.batch_id}</strong>
                        <div className="cell-sub">{item?.name ?? b.item_id}</div>
                      </td>
                      <td>
                        <code>{b.expiry_date ?? 'Non-Expiring'}</code>
                      </td>
                      <td>
                        <QualityStateBadge state={b.quality_state} />
                        {b.quarantine_reason && (
                          <div className="cell-sub">{b.quarantine_reason}</div>
                        )}
                      </td>
                      <td>
                        <div className="font-mono">
                          Phys: {b.physical_qty_base} {item?.base_unit}
                        </div>
                        <div className="cell-sub">
                          Dmg: {b.damaged_qty_base} | Quar: {b.quarantined_qty_base} | Exp:{' '}
                          {b.expired_qty_base}
                        </div>
                      </td>
                      <td>
                        {b.quality_state === 'QUARANTINED' || b.quarantined_qty_base > 0 ? (
                          <button
                            type="button"
                            className="btn btn-sm btn-warning"
                            onClick={() => handleQaReleaseBatch(b)}
                            title="Test Scenario 5: Succeeds for Maj. Dr. S. Iyer (MEDICAL_QA_OFFICER), blocked 403 for Storekeeper/Approver"
                          >
                            <ShieldAlert size={13} />
                            <span>Release Quarantine (QA Only)</span>
                          </button>
                        ) : (
                          <span className="cell-sub">No QA hold</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* CSV Import Validation & Physical Count Adjustment */}
        <section className="panel">
          <div className="panel-header-row">
            <div>
              <h3>
                <FileSpreadsheet size={17} /> CSV Evidence Import &amp; Compensating Count Adjustment
              </h3>
              <p className="panel-subtext">
                Validates CSV vouchers before commit (`POST /api/v1/imports/validate`). Unknown units, unknown batches, negative quantities, and duplicate keys are quarantined (Scenario 7).
              </p>
            </div>
          </div>

          <div className="button-row" style={{ marginBottom: '0.75rem' }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleRunCsvValidate}
            >
              <Upload size={14} />
              <span>1. Validate Sample CSV Batch (5 Rows)</span>
            </button>
            {csvPreview && !csvPreview.committed && (
              <button
                type="button"
                className="btn btn-success"
                onClick={handleCommitCsv}
              >
                <CheckCircle2 size={14} />
                <span>2. Commit {csvPreview.valid_count} Valid Rows Once</span>
              </button>
            )}
          </div>

          {csvPreview && (
            <div className="csv-preview-box">
              <div className="csv-preview-summary">
                <strong>Preview {csvPreview.validation_id}:</strong> {csvPreview.valid_count} Valid,{' '}
                {csvPreview.quarantined_count} Quarantined • Status:{' '}
                <code>{csvPreview.committed ? 'COMMITTED' : 'PREVIEW_ONLY'}</code>
              </div>
              <div className="table-scroll">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Item / Batch</th>
                      <th>Raw Input</th>
                      <th>Status &amp; Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {csvPreview.rows.map((r) => (
                      <tr key={r.row.row_number}>
                        <td>#{r.row.row_number}</td>
                        <td>
                          <code>{r.row.raw_item_id}</code>
                          <div className="cell-sub">{r.row.raw_batch_id}</div>
                        </td>
                        <td>
                          {r.row.raw_event_type}: {r.row.raw_quantity} {r.row.raw_unit}
                        </td>
                        <td>
                          {r.status === 'VALID' ? (
                            <span className="badge badge-success">
                              VALID ({r.converted_qty_base} base units)
                            </span>
                          ) : (
                            <div>
                              <span className="badge badge-danger">{r.error_code}</span>
                              <div className="cell-sub text-danger">{r.error_reason}</div>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <hr className="divider" />

          <h4>
            <ClipboardCheck size={16} /> Record Physical Count / Compensating Adjustment
          </h4>
          <p className="panel-subtext">
            Corrections append a compensating event with authority and reason; historical events are never rewritten.
          </p>
          <form onSubmit={handleCompensatingAdjustment} className="compact-form">
            <div className="form-row-3">
              <div>
                <label className="form-label">Target Batch</label>
                <select
                  className="form-select"
                  value={adjustBatchId}
                  onChange={(e) => setAdjustBatchId(e.target.value)}
                >
                  {batches.map((b) => (
                    <option key={b.batch_id} value={b.batch_id}>
                      {b.batch_id} ({b.item_id}) — Phys: {b.physical_qty_base}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="form-label">Delta Quantity (Base Units)</label>
                <input
                  type="number"
                  className="form-input"
                  value={adjustDeltaBase}
                  onChange={(e) => setAdjustDeltaBase(Number(e.target.value))}
                />
              </div>
              <div>
                <label className="form-label">Idempotency Event Key</label>
                <input
                  type="text"
                  className="form-input font-mono"
                  value={adjustClientKey}
                  onChange={(e) => setAdjustClientKey(e.target.value)}
                />
              </div>
            </div>
            <div className="form-row-2" style={{ marginTop: '0.5rem' }}>
              <input
                type="text"
                className="form-input"
                placeholder="Mandatory audit reason for compensating adjustment..."
                value={adjustReason}
                onChange={(e) => setAdjustReason(e.target.value)}
              />
              <button type="submit" className="btn btn-secondary">
                Append Compensating Event ({events.length} in ledger)
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
};
