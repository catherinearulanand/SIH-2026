/**
 * Setu Supply (SIH26251) — Tab 4: Independent Approval, Atomic Reservation, Dispatch & Partial Receipt Reconciliation
 */

import React, { useState } from 'react';
import {
  AlertOctagon,
  CheckCircle2,
  Lock,
  PackageCheck,
  Repeat,
  ShieldCheck,
  Truck,
  UserCheck,
} from 'lucide-react';
import {
  ApiErrorEnvelope,
  AuthenticatedPersona,
  InventoryProjection,
  Item,
  ReplenishmentRequest,
  ShipmentLine,
  Site,
  SiteSnapshot,
} from '../contracts/api';
import {
  QuantityDisplay,
  RequestStateBadge,
  ShipmentStateBadge,
} from '../components/StatusBadges';
import { setuApiClient } from '../services/apiClient';
import { loadEngineState } from '../services/mockContractEngine';

interface ApprovalFulfilmentViewProps {
  persona: AuthenticatedPersona;
  site: Site;
  snapshot: SiteSnapshot;
  items: Item[];
  projections: InventoryProjection[];
  onRefreshState: () => void;
  onNotify: (msg: string, tone: 'success' | 'error' | 'info') => void;
}

export const ApprovalFulfilmentView: React.FC<ApprovalFulfilmentViewProps> = ({
  persona,
  site,
  snapshot,
  items,
  projections,
  onRefreshState,
  onNotify,
}) => {
  const engineState = loadEngineState();
  const siteRequests = engineState.requests.filter((r) => r.site_id === site.site_id);
  const siteShipments = engineState.shipments.filter((s) => s.site_id === site.site_id);

  const [approvalReason, setApprovalReason] = useState<string>(
    'Verified against 180-day holdout forecast, GIS storage split-arrival plan, and current usable stock.'
  );
  const [ackStaleGate, setAckStaleGate] = useState<boolean>(false);
  const [reserveQtyBase, setReserveQtyBase] = useState<number>(240);

  // Partial receipt form state
  const [selectedShipmentId, setSelectedShipmentId] = useState<string>(
    siteShipments[0]?.shipment_id ?? 'SHP-2026-901'
  );
  const [receiptPartId, setReceiptPartId] = useState<string>('RCPT-901-PART2');
  const [receiptClientKey, setReceiptClientKey] = useState<string>('CEV-RCPT-901-P2');
  const [acceptedBase, setAcceptedBase] = useState<number>(216); // 9 Crates accepted
  const [damagedBase, setDamagedBase] = useState<number>(24); // 1 Crate damaged (216+24 = 240 remaining!)
  const [rejectedBase, setRejectedBase] = useState<number>(0);
  const [quarantineSubsetBase, setQuarantineSubsetBase] = useState<number>(24);
  const [receiptNotes, setReceiptNotes] = useState<string>(
    'Tail convoy vehicle arrived; 9 Crates accepted usable, 1 Crate transit-damaged & quarantined.'
  );
  const [allowOverage, setAllowOverage] = useState<boolean>(false);

  const itemMap = new Map(items.map((i) => [i.item_id, i]));
  const activeShipment =
    siteShipments.find((s) => s.shipment_id === selectedShipmentId) ?? siteShipments[0];

  const handleApproveDecision = async (
    req: ReplenishmentRequest,
    decision: 'APPROVED' | 'REJECTED' | 'APPROVED_WITH_CHANGE'
  ) => {
    try {
      const res = await setuApiClient.approveRequest(persona, req.request_id, {
        decision,
        approved_qty_base:
          decision === 'APPROVED_WITH_CHANGE'
            ? Math.round(req.proposed_qty_base * 0.75)
            : req.proposed_qty_base,
        reason: approvalReason,
        acknowledge_stale_gate: ackStaleGate,
      });
      onRefreshState();
      onNotify(
        `Request ${res.request.request_id} ${decision} by ${persona.display_name} at Ledger v${res.request.approval_decision?.revalidated_snapshot_version}.${
          res.shipment_created ? ` Created Shipment ${res.shipment_created.shipment_id}.` : ''
        }`,
        'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Approval denied by server policy', 'error');
    }
  };

  const handleReserveStock = async (req: ReplenishmentRequest, customQty?: number) => {
    try {
      const updated = await setuApiClient.reserveRequestStock(persona, req.request_id, {
        reserve_qty_base: customQty ?? reserveQtyBase,
        expected_version: snapshot.version,
      });
      onRefreshState();
      onNotify(
        `Atomically reserved ${customQty ?? reserveQtyBase} base units for ${updated.request_id}.`,
        'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Atomic reservation rejected', 'error');
    }
  };

  const handleDispatchShipment = async (shp: ShipmentLine) => {
    try {
      await setuApiClient.recordShipmentDispatch(persona, shp.shipment_id, {
        dispatched_quantity_base: shp.authorized_quantity_base,
        expected_arrival_date: shp.expected_arrival_date,
        notes: 'Handover verified at Rear Supply Hub gate',
      });
      onRefreshState();
      onNotify(
        `Recorded dispatch handover for ${shp.shipment_id} (${shp.authorized_quantity_base} base units). Note: Incoming goods do NOT increase on-hand stock until receipt!`,
        'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Dispatch recording failed', 'error');
    }
  };

  const handleSubmitReceiptPart = async (overrideParams?: {
    receipt_part_id?: string;
    client_event_id?: string;
    accepted_base?: number;
    damaged_base?: number;
    rejected_base?: number;
    quarantine_quantity_base?: number;
    notes?: string;
  }) => {
    if (!activeShipment) return;
    try {
      const res = await setuApiClient.recordReceiptPart(
        persona,
        activeShipment.shipment_id,
        {
          receipt_part_id: overrideParams?.receipt_part_id ?? receiptPartId,
          client_event_id: overrideParams?.client_event_id ?? receiptClientKey,
          accepted_base: overrideParams?.accepted_base ?? acceptedBase,
          damaged_base: overrideParams?.damaged_base ?? damagedBase,
          rejected_base: overrideParams?.rejected_base ?? rejectedBase,
          quarantine_quantity_base:
            overrideParams?.quarantine_quantity_base ?? quarantineSubsetBase,
          evidence_ref: `VOUCHER-${overrideParams?.receipt_part_id ?? receiptPartId}`,
          notes: overrideParams?.notes ?? receiptNotes,
          allow_discrepancy_overage: allowOverage,
        }
      );
      onRefreshState();

      if ('queued_offline' in res && res.queued_offline) {
        onNotify(
          `Offline Mode (Video 2:05–2:35): Captured Provisional Receipt Part (${res.queued_offline.client_event_id}) in IndexedDB. Reconnect & click Sync Queue to validate!`,
          'info'
        );
      } else if (res.idempotent_replay) {
        onNotify(
          `Idempotent Replay Verified (Scenario 1): Receipt key '${
            overrideParams?.client_event_id ?? receiptClientKey
          }' was already processed. Stock increased ONCE only; zero duplicate effect!`,
          'info'
        );
      } else if ('receipt_part' in res && res.receipt_part) {
        onNotify(
          `Recorded Receipt Part ${res.receipt_part.receipt_part_id} on ${activeShipment.shipment_id} -> Shipment state: ${res.shipment.state}.`,
          'success'
        );
        setReceiptPartId(`RCPT-901-PART${res.shipment.receipt_parts.length + 1}`);
        setReceiptClientKey(`CEV-RCPT-901-P${res.shipment.receipt_parts.length + 1}`);
      }
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Receipt part rejected', 'error');
    }
  };

  return (
    <div className="view-stack">
      {/* Top Section: Independent Approval & Atomic Stock Reservation */}
      <section className="panel panel-highlight">
        <div className="panel-header-row">
          <div>
            <div className="eyebrow">
              <UserCheck size={14} /> SECTION 5, 9 &amp; 11 — INDEPENDENT HUMAN REVIEW &amp; ATOMIC RESERVATION BOUNDARY
            </div>
            <h2>Replenishment Requests • Creator ≠ Approver Enforcement • Online Revalidation</h2>
            <p className="panel-subtext">
              <strong>Separation of Duties (Scenario 4):</strong> The creator of a request (`STOREKEEPER` / `PLANNER`) is blocked by the server (`403 SELF_APPROVAL_PROHIBITED`) from approving their own request. Switch identity in the top bar to <strong>Maj. A. Verma (Independent Approver)</strong> to approve.
            </p>
          </div>
        </div>

        <div className="form-row-2" style={{ marginBottom: '0.75rem' }}>
          <div>
            <label className="form-label">Approver Decision Rationale (Recorded in Audit Log):</label>
            <input
              type="text"
              className="form-input"
              value={approvalReason}
              onChange={(e) => setApprovalReason(e.target.value)}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '1rem' }}>
            <label className="checkbox-inline">
              <input
                type="checkbox"
                checked={ackStaleGate}
                onChange={(e) => setAckStaleGate(e.target.checked)}
              />
              <span>Acknowledge Stale Snapshot Exception (Scenario 9 Gate)</span>
            </label>
            <div>
              <label className="form-label">Atomic Reserve Qty (Base)</label>
              <input
                type="number"
                className="form-input"
                style={{ width: '120px' }}
                value={reserveQtyBase}
                onChange={(e) => setReserveQtyBase(Number(e.target.value))}
              />
            </div>
          </div>
        </div>

        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Request ID &amp; Lineage</th>
                <th>Item &amp; Proposed Qty</th>
                <th>Creator Identity</th>
                <th>Status &amp; Approval Decision</th>
                <th>Reservation State</th>
                <th>Review &amp; Atomic Reservation Actions</th>
              </tr>
            </thead>
            <tbody>
              {siteRequests.map((req) => {
                const item = itemMap.get(req.item_id);
                const proj = projections.find((p) => p.item_id === req.item_id);
                const isSelf = req.creator_id === persona.user_id;
                return (
                  <tr key={req.request_id}>
                    <td>
                      <strong>{req.request_id}</strong>
                      <div className="cell-sub">
                        Rec: <code>{req.source_recommendation_id}</code>
                      </div>
                      {req.source_plan_id && (
                        <div className="cell-sub">
                          GIS Plan: <code>{req.source_plan_id}</code>
                        </div>
                      )}
                    </td>
                    <td>
                      <QuantityDisplay qtyBase={req.proposed_qty_base} item={item} />
                      {req.override_reason && (
                        <div className="cell-sub text-warn">
                          Override: {req.override_reason}
                        </div>
                      )}
                    </td>
                    <td>
                      <strong>{req.creator_name}</strong>
                      <div className="cell-sub">
                        <code>{req.creator_id}</code> [{req.creator_role}]
                      </div>
                    </td>
                    <td>
                      <RequestStateBadge
                        state={req.state}
                        isProvisional={req.is_provisional_offline}
                      />
                      {req.approval_decision && (
                        <div className="cell-sub">
                          By {req.approval_decision.approver_name} (v
                          {req.approval_decision.revalidated_snapshot_version}): &ldquo;
                          {req.approval_decision.reason}&rdquo;
                        </div>
                      )}
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          req.reservation_state === 'RESERVED'
                            ? 'badge-success'
                            : 'badge-neutral'
                        }`}
                      >
                        <Lock size={12} />
                        <span>
                          {req.reservation_state} ({req.reserved_qty_base} {item?.base_unit})
                        </span>
                      </span>
                      <div className="cell-sub">
                        Site Allocatable: {proj?.allocatable_base ?? 0} {item?.base_unit}
                      </div>
                    </td>
                    <td>
                      {req.state === 'SUBMITTED' && (
                        <div className="button-stack">
                          <button
                            type="button"
                            className={`btn btn-sm ${
                              isSelf ? 'btn-warning' : 'btn-success'
                            }`}
                            onClick={() => handleApproveDecision(req, 'APPROVED')}
                            title={
                              isSelf
                                ? 'Click to demonstrate Scenario 4: Creator self-approval blocked (403)'
                                : 'Approve request as independent authority'
                            }
                          >
                            <ShieldCheck size={13} />
                            <span>
                              {isSelf
                                ? 'Approve (Test Self-Approval 403)'
                                : 'Approve Request'}
                            </span>
                          </button>
                          <div className="button-row">
                            <button
                              type="button"
                              className="btn btn-sm btn-secondary"
                              onClick={() =>
                                handleApproveDecision(req, 'APPROVED_WITH_CHANGE')
                              }
                            >
                              Approve w/ 75% Cap
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={() => handleApproveDecision(req, 'REJECTED')}
                            >
                              Reject
                            </button>
                          </div>
                        </div>
                      )}

                      {req.state === 'APPROVED' && (
                        <div className="button-stack">
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            onClick={() => handleReserveStock(req)}
                          >
                            <Lock size={13} />
                            <span>
                              Reserve {reserveQtyBase} {item?.base_unit}
                            </span>
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-warning"
                            onClick={() =>
                              handleReserveStock(req, (proj?.allocatable_base ?? 1000) + 500)
                            }
                            title="Test Scenario 2: Attempt to reserve more than allocatable stock -> Blocked 409"
                          >
                            <span>Test Over-Allocation (Scenario 2)</span>
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Bottom Section: Shipments, Dispatch Handover & Partial Receipt Reconciliation */}
      <div className="two-col-grid">
        {/* Left: Shipments & Unresolved Balance Table */}
        <section className="panel">
          <h3>
            <Truck size={17} /> Authorized Shipments &amp; Partial Fulfilment Status
          </h3>
          <p className="panel-subtext">
            <strong>Accounting Rule:</strong> An approved request is not a receipt. Incoming goods do not increase on-hand stock until receipt parts are recorded and dispositions are validated.
          </p>

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Shipment / Request</th>
                  <th>Item &amp; Batch</th>
                  <th>Dispatched vs Accounted</th>
                  <th>Unresolved Balance</th>
                  <th>State &amp; Action</th>
                </tr>
              </thead>
              <tbody>
                {siteShipments.map((shp) => {
                  const item = itemMap.get(shp.item_id);
                  const accSum = shp.receipt_parts.reduce(
                    (s, p) => s + p.accepted_base,
                    0
                  );
                  const dmgSum = shp.receipt_parts.reduce((s, p) => s + p.damaged_base, 0);
                  const rejSum = shp.receipt_parts.reduce(
                    (s, p) => s + p.rejected_base,
                    0
                  );
                  const totalAccounted = accSum + dmgSum + rejSum;
                  const unresolved = Math.max(
                    0,
                    shp.dispatched_quantity_base - totalAccounted
                  );

                  return (
                    <tr
                      key={shp.shipment_id}
                      className={
                        activeShipment?.shipment_id === shp.shipment_id
                          ? 'row-selected'
                          : ''
                      }
                    >
                      <td>
                        <strong>{shp.shipment_id}</strong>
                        <div className="cell-sub">
                          Req: <code>{shp.request_id}</code>
                        </div>
                        <div className="cell-sub">ETA: {shp.expected_arrival_date}</div>
                      </td>
                      <td>
                        <div>{item?.name ?? shp.item_id}</div>
                        <div className="cell-sub">
                          Batch: <code>{shp.batch_id}</code>
                        </div>
                      </td>
                      <td>
                        <div className="font-mono">
                          Dispatched: {shp.dispatched_quantity_base} {item?.base_unit}
                        </div>
                        <div className="cell-sub">
                          Acc: {accSum} | Dmg: {dmgSum} | Rej: {rejSum} (
                          {shp.receipt_parts.length} parts)
                        </div>
                      </td>
                      <td>
                        <QuantityDisplay
                          qtyBase={unresolved}
                          item={item}
                          highlight={unresolved > 0 ? 'warning' : 'usable'}
                        />
                      </td>
                      <td>
                        <ShipmentStateBadge state={shp.state} />
                        <div className="button-row" style={{ marginTop: '0.4rem' }}>
                          {shp.state === 'CREATED' && (
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              onClick={() => handleDispatchShipment(shp)}
                            >
                              Record Dispatch
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => setSelectedShipmentId(shp.shipment_id)}
                          >
                            Select for Receipt
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* Right: Partial Receipt & Discrepancy Reconciliation Form */}
        <section className="panel">
          <h3>
            <PackageCheck size={17} /> Partial Receipt &amp; Disposition Reconciliation (`POST /api/v1/shipments/{'{id}'}/receipt-parts`)
          </h3>
          <p className="panel-subtext">
            <strong>Section 11 Partition Invariant:</strong> <code>Accepted</code>,{' '}
            <code>Damaged</code>, and <code>Rejected</code> partition each received part.{' '}
            <code>Quarantine</code> is a status subset on physically received goods (never counted twice).
          </p>

          {activeShipment && (
            <>
              <div className="preset-strip" style={{ marginBottom: '0.75rem' }}>
                <span className="preset-label">Scenario 1 &amp; 6 One-Click Verifiers:</span>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() =>
                    handleSubmitReceiptPart({
                      receipt_part_id: 'RCPT-901-PART1',
                      client_event_id: 'CEV-RCPT-901-P1',
                      accepted_base: 576,
                      damaged_base: 48,
                      rejected_base: 0,
                      quarantine_quantity_base: 48,
                      notes: 'Exact retry of Part 1',
                    })
                  }
                >
                  <Repeat size={13} />
                  <span>1. Retry Duplicate Key CEV-RCPT-901-P1 (Idempotent)</span>
                </button>

                <button
                  type="button"
                  className="btn btn-sm btn-warning"
                  onClick={() =>
                    handleSubmitReceiptPart({
                      receipt_part_id: 'RCPT-901-PART1-MOD',
                      client_event_id: 'CEV-RCPT-901-P1',
                      accepted_base: 900, // Modified payload on existing key!
                      damaged_base: 0,
                      rejected_base: 0,
                      quarantine_quantity_base: 0,
                      notes: 'Modified payload with reused key',
                    })
                  }
                >
                  <AlertOctagon size={13} />
                  <span>2. Reuse Key w/ Altered Payload (Reject 409)</span>
                </button>

                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() =>
                    handleSubmitReceiptPart({
                      receipt_part_id: 'RCPT-901-OVERAGE',
                      client_event_id: `CEV-OVER-${Date.now()}`,
                      accepted_base: 600, // Exceeds 240 remaining!
                      damaged_base: 0,
                      rejected_base: 0,
                      quarantine_quantity_base: 0,
                      notes: 'Exceeds dispatched quantity without discrepancy sign-off',
                    })
                  }
                >
                  <span>3. Test Receipt &gt; Dispatched (Reject 422)</span>
                </button>
              </div>

              <div className="compact-form">
                <div className="form-row-3">
                  <div>
                    <label className="form-label">Target Shipment</label>
                    <input
                      type="text"
                      className="form-input font-mono"
                      value={`${activeShipment.shipment_id} (${activeShipment.item_id})`}
                      readOnly
                    />
                  </div>
                  <div>
                    <label className="form-label">New Receipt Part ID (Split Delivery)</label>
                    <input
                      type="text"
                      className="form-input font-mono"
                      value={receiptPartId}
                      onChange={(e) => setReceiptPartId(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="form-label">Idempotency Key (`client_event_id`)</label>
                    <input
                      type="text"
                      className="form-input font-mono"
                      value={receiptClientKey}
                      onChange={(e) => setReceiptClientKey(e.target.value)}
                    />
                  </div>
                </div>

                <div className="form-row-4" style={{ marginTop: '0.5rem' }}>
                  <div>
                    <label className="form-label">Accepted (Usable Base)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={acceptedBase}
                      onChange={(e) => setAcceptedBase(Number(e.target.value))}
                    />
                  </div>
                  <div>
                    <label className="form-label">Damaged (Held Base)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={damagedBase}
                      onChange={(e) => setDamagedBase(Number(e.target.value))}
                    />
                  </div>
                  <div>
                    <label className="form-label">Rejected (Turned Away)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={rejectedBase}
                      onChange={(e) => setRejectedBase(Number(e.target.value))}
                    />
                  </div>
                  <div>
                    <label className="form-label">Quarantine Subset (≤ Acc+Dmg)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={quarantineSubsetBase}
                      onChange={(e) => setQuarantineSubsetBase(Number(e.target.value))}
                    />
                  </div>
                </div>

                <div className="form-row-2" style={{ marginTop: '0.5rem' }}>
                  <input
                    type="text"
                    className="form-input"
                    value={receiptNotes}
                    onChange={(e) => setReceiptNotes(e.target.value)}
                    placeholder="Condition & discrepancy notes..."
                  />
                  <div className="button-row">
                    <label className="checkbox-inline">
                      <input
                        type="checkbox"
                        checked={allowOverage}
                        onChange={(e) => setAllowOverage(e.target.checked)}
                      />
                      <span>Authorize Overage Discrepancy</span>
                    </label>
                    <button
                      type="button"
                      className="btn btn-success"
                      onClick={() => handleSubmitReceiptPart()}
                    >
                      <CheckCircle2 size={14} />
                      <span>Record Receipt Part</span>
                    </button>
                  </div>
                </div>
              </div>

              <h4 style={{ marginTop: '0.9rem' }}>
                Recorded Receipt Parts on {activeShipment.shipment_id}
              </h4>
              <div className="table-scroll">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>Part ID &amp; Key</th>
                      <th>Accepted</th>
                      <th>Damaged</th>
                      <th>Rejected</th>
                      <th>Quarantine Subset</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeShipment.receipt_parts.map((pt) => (
                      <tr key={pt.receipt_part_id}>
                        <td>
                          <strong>{pt.receipt_part_id}</strong>
                          <div className="cell-sub">
                            <code>{pt.client_event_id}</code>
                          </div>
                        </td>
                        <td className="font-mono">{pt.accepted_base}</td>
                        <td className="font-mono">{pt.damaged_base}</td>
                        <td className="font-mono">{pt.rejected_base}</td>
                        <td className="font-mono">{pt.quarantine_quantity_base}</td>
                        <td className="cell-sub">{pt.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
};
