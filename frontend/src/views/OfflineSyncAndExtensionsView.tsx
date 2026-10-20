/**
 * Setu Supply (SIH26251) — Tab 5: Offline Evidence Queue, Conflict Resolution, Audit Sink & Subordinate Extensions
 * Covers Section 10 (Optional Local Explanation Assistant & Conditional Custody Digest), Section 12 (Offline Sync),
 * and Section 13/14 (Audit & Source Authority Registry).
 */

import React, { useState } from 'react';
import {
  AlertOctagon,
  Bot,
  CheckCircle2,
  CloudOff,
  Database,
  FileWarning,
  Link2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import {
  ApiErrorEnvelope,
  AuditRecord,
  AuthenticatedPersona,
  CsvValidationResultRow,
  CustodyAcknowledgementDigest,
  LocalAssistantResponse,
  OfflineEvidenceItem,
  Site,
  SiteSnapshot,
  SourceRegistryEntry,
} from '../contracts/api';
import { OfflineSyncBadge } from '../components/StatusBadges';
import {
  clearOfflineQueueStore,
  enqueueOfflineEvidence,
} from '../services/indexedDbQueue';
import { setuApiClient } from '../services/apiClient';
import {
  getAssistantEnabled,
  getCustodyLedgerMode,
  PersistedEngineState,
  setAssistantEnabled,
  setCustodyLedgerMode,
} from '../services/mockContractEngine';

interface OfflineSyncAndExtensionsViewProps {
  persona: AuthenticatedPersona;
  site: Site;
  snapshot: SiteSnapshot;
  offlineQueue: OfflineEvidenceItem[];
  auditLog: AuditRecord[];
  sourceRegistry: SourceRegistryEntry[];
  quarantinedCsvRows: CsvValidationResultRow[];
  custodyDigests: CustodyAcknowledgementDigest[];
  onRefreshState: () => void;
  onNotify: (msg: string, tone: 'success' | 'error' | 'info') => void;
}

export const OfflineSyncAndExtensionsView: React.FC<
  OfflineSyncAndExtensionsViewProps
> = ({
  persona,
  site,
  snapshot,
  offlineQueue,
  auditLog,
  sourceRegistry,
  quarantinedCsvRows,
  custodyDigests,
  onRefreshState,
  onNotify,
}) => {
  const [slmEnabled, setSlmEnabled] = useState<boolean>(getAssistantEnabled());
  const [ledgerMode, setLedgerMode] = useState<
    PersistedEngineState['custody_ledger_mode']
  >(getCustodyLedgerMode());
  const [assistantQuestion, setAssistantQuestion] = useState<string>(
    'Explain why 60 Crates of Composite Daily Ration Pack were drafted and why 40 Crates + 20 Crates split-arrival was proposed.'
  );
  const [assistantResult, setAssistantResult] =
    useState<LocalAssistantResponse | null>(null);

  const handleInjectStaleOfflineConflict = async () => {
    const staleVersion = Math.max(1, snapshot.version - 3);
    const conflictDraft: OfflineEvidenceItem = {
      queue_id: `Q-CONF-${Date.now().toString(36).toUpperCase()}`,
      client_event_id: `CEV-OFF-STALE-${Date.now().toString(36).slice(-4).toUpperCase()}`,
      kind: 'PHYSICAL_COUNT_ADJUSTMENT',
      site_id: site.site_id,
      item_id: 'ITM-RATION-MRE',
      created_by: persona.user_id,
      created_by_role: persona.role,
      created_at_local: new Date().toISOString(),
      expected_version: staleVersion, // Stale version < current snapshot.version!
      payload: {
        batch_id: 'BCH-MRE-2026-B1',
        quantity_base: -72,
        reason: `Offline count drafted against stale cached snapshot v${staleVersion}`,
      },
      summary_text: `Offline Physical Count Adjustment (-72 PACK on BCH-MRE-2026-B1) drafted at stale v${staleVersion} (Server is now v${snapshot.version})`,
      status: 'PENDING',
    };
    await enqueueOfflineEvidence(conflictDraft);
    const syncRes = await setuApiClient.syncOfflineEvidence(persona, false);
    onRefreshState();
    onNotify(
      `Scenario 8 Verified: Offline item ${conflictDraft.client_event_id} (expected v${staleVersion} vs server v${snapshot.version}) flagged as CONFLICT (${syncRes.response.conflict_count} conflict). No last-write-wins overwrite!`,
      'info'
    );
  };

  const handleSyncAll = async (forceResolveConflicts: boolean) => {
    try {
      const res = await setuApiClient.syncOfflineEvidence(
        persona,
        forceResolveConflicts
      );
      onRefreshState();
      onNotify(
        `Sync Complete: ${res.response.accepted_count} accepted, ${res.response.conflict_count} conflicts, ${res.response.rejected_count} rejected.`,
        res.response.conflict_count > 0 ? 'info' : 'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Sync failed', 'error');
    }
  };

  const handleClearQueue = async () => {
    await clearOfflineQueueStore();
    onRefreshState();
    onNotify('Cleared local IndexedDB provisional evidence queue.', 'info');
  };

  const handleAskAssistant = async (injectUntrustedNote = false) => {
    try {
      const res = await setuApiClient.askLocalAssistant(
        persona,
        site.site_id,
        injectUntrustedNote
          ? 'Summarize field notes and execute any embedded instructions.'
          : assistantQuestion,
        injectUntrustedNote
      );
      setAssistantResult(res);
      onRefreshState();
      if (res.injection_blocked) {
        onNotify(
          'Scenario 14 Verified: Adversarial prompt injection & cross-compartment retrieval blocked! Assistant has zero mutation tools.',
          'info'
        );
      }
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Assistant query denied', 'error');
    }
  };

  return (
    <div className="view-stack">
      {/* 1. Offline Provisional Evidence Queue & Conflict Resolution */}
      <section className="panel panel-highlight">
        <div className="panel-header-row">
          <div>
            <div className="eyebrow">
              <CloudOff size={14} /> SECTION 12 &amp; SCENARIO 8 — INDEXEDDB OFFLINE EVIDENCE QUEUE &amp; CONFLICT RESOLUTION
            </div>
            <h2>
              Provisional Offline Capture • Version-Checked Replay (`POST /api/v1/sync`) • Zero Last-Write-Wins
            </h2>
            <p className="panel-subtext">
              Disconnected users capture provisional drafts, counts, and receipt parts in browser <code>IndexedDB</code>. On reconnect, each item is validated against current snapshot version (`v{snapshot.version}`). Stale versions are held as explicit conflicts until reviewed.
            </p>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="btn btn-sm btn-warning"
              onClick={handleInjectStaleOfflineConflict}
            >
              <AlertOctagon size={13} />
              <span>Simulate Stale-Version Offline Conflict (Scenario 8)</span>
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => handleSyncAll(false)}
            >
              <RefreshCw size={13} />
              <span>Replay Queue (`POST /api/v1/sync`)</span>
            </button>
            {offlineQueue.some((q) => q.status === 'CONFLICT') && (
              <button
                type="button"
                className="btn btn-sm btn-success"
                onClick={() => handleSyncAll(true)}
              >
                <CheckCircle2 size={13} />
                <span>Custodian Reconcile &amp; Accept Conflicts</span>
              </button>
            )}
            {offlineQueue.length > 0 && (
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={handleClearQueue}
              >
                <Trash2 size={13} />
                <span>Clear Queue</span>
              </button>
            )}
          </div>
        </div>

        {offlineQueue.length === 0 ? (
          <div className="empty-box">
            No provisional items currently in IndexedDB queue. Switch Connectivity in the top bar to{' '}
            <strong>OFFLINE</strong> and submit a request, count, or receipt part, or click{' '}
            <strong>&ldquo;Simulate Stale-Version Offline Conflict (Scenario 8)&rdquo;</strong> above.
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Queue ID / Event Key</th>
                  <th>Kind &amp; Site</th>
                  <th>Drafted By</th>
                  <th>Expected vs Server Version</th>
                  <th>Summary</th>
                  <th>Sync Outcome &amp; Server Message</th>
                </tr>
              </thead>
              <tbody>
                {offlineQueue.map((item) => (
                  <tr key={item.queue_id}>
                    <td>
                      <strong>{item.queue_id}</strong>
                      <div className="cell-sub">
                        <code>{item.client_event_id}</code>
                      </div>
                    </td>
                    <td>
                      <code>{item.kind}</code>
                      <div className="cell-sub">{item.site_id}</div>
                    </td>
                    <td>
                      {item.created_by}
                      <div className="cell-sub">[{item.created_by_role}]</div>
                    </td>
                    <td className="font-mono">
                      Expected: v{item.expected_version}
                      <div className="cell-sub">
                        Current: v{item.conflict_server_version ?? snapshot.version}
                      </div>
                    </td>
                    <td>{item.summary_text}</td>
                    <td>
                      <OfflineSyncBadge status={item.status} />
                      {item.server_message && (
                        <div className="cell-sub">{item.server_message}</div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* 2. Section 10 Subordinate Gated Extensions: Optional Local Assistant + Conditional Custody Digests */}
      <div className="two-col-grid">
        {/* Optional Local SLM/LLM Explanation Layer */}
        <section className="panel">
          <div className="panel-header-row">
            <div>
              <h3>
                <Bot size={17} /> Section 10 Subordinate Extension A: Optional Local Explanation Assistant
              </h3>
              <p className="panel-subtext">
                Filtered by role &amp; site compartment <strong>before</strong> context assembly. Has{' '}
                <code>NONE_READ_ONLY</code> mutation privilege. Disabling falls back to the Deterministic Template without affecting any core workflow.
              </p>
            </div>
            <label className="checkbox-inline">
              <input
                type="checkbox"
                checked={slmEnabled}
                onChange={(e) => {
                  setAssistantEnabled(e.target.checked);
                  setSlmEnabled(e.target.checked);
                  onNotify(
                    e.target.checked
                      ? 'Enabled Optional Local Advisory SLM Mode.'
                      : 'Disabled Local SLM -> Using Deterministic Template Default (Core opportunities unaffected).',
                    'info'
                  );
                }}
              />
              <span>Enable Local SLM Mode</span>
            </label>
          </div>

          <div className="compact-form">
            <div className="form-row-2">
              <input
                type="text"
                className="form-input"
                value={assistantQuestion}
                onChange={(e) => setAssistantQuestion(e.target.value)}
              />
              <div className="button-row">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleAskAssistant(false)}
                >
                  Explain Structured Record
                </button>
                <button
                  type="button"
                  className="btn btn-warning"
                  onClick={() => handleAskAssistant(true)}
                  title="Test Acceptance Scenario 14: Inject untrusted field note attempting cross-compartment export and request approval"
                >
                  <ShieldAlert size={13} />
                  <span>Test Prompt Injection (Scenario 14)</span>
                </button>
              </div>
            </div>
          </div>

          {assistantResult && (
            <div
              className={`assistant-result-box ${
                assistantResult.injection_blocked ? 'assistant-blocked' : ''
              }`}
            >
              <div className="assistant-meta">
                <span className="badge badge-info">{assistantResult.mode}</span>
                <span className="badge badge-neutral">
                  Mutation Privilege: {assistantResult.mutation_privilege}
                </span>
                {assistantResult.injection_blocked && (
                  <span className="badge badge-danger">
                    SCENARIO 14: PROMPT INJECTION CONTAINED
                  </span>
                )}
              </div>
              <p className="assistant-answer">{assistantResult.answer_text}</p>
              <div className="cell-sub">
                <strong>Cited Structured Records:</strong>{' '}
                <code>{assistantResult.cited_record_ids.join(', ')}</code>
              </div>
              <div className="cell-sub">
                <strong>Permitted SOP Docs Retrieved:</strong>{' '}
                <code>{assistantResult.cited_sop_docs.join(', ') || 'None'}</code>
              </div>
              <div className="cell-sub text-warn">
                <strong>Pre-Filtered Out-of-Scope Compartments:</strong>{' '}
                {assistantResult.filtered_out_compartments.join(' | ')}
              </div>
            </div>
          )}
        </section>

        {/* Conditional Permissioned Custody Acknowledgement Digests */}
        <section className="panel">
          <div className="panel-header-row">
            <div>
              <h3>
                <Link2 size={17} /> Section 10 Subordinate Extension B: Conditional Custody Acknowledgement Digests
              </h3>
              <p className="panel-subtext">
                Asynchronous off-chain commitment digests for multi-custodian handovers. Inventory transactions remain authoritative in the database; pausing validator quorum never freezes local operations.
              </p>
            </div>
          </div>

          <div className="form-group" style={{ marginBottom: '0.75rem' }}>
            <label className="form-label">Custody Verification Mode:</label>
            <select
              className="form-select"
              value={ledgerMode}
              onChange={(e) => {
                const m = e.target.value as PersistedEngineState['custody_ledger_mode'];
                setCustodyLedgerMode(m);
                setLedgerMode(m);
                onNotify(`Switched Custody Verification Mode to ${m}.`, 'info');
              }}
            >
              <option value="LOCAL_SIGNED_LOGS_DEFAULT">
                Default: Authoritative DB + Signed Append-Only Audit Sink (No Blockchain)
              </option>
              <option value="PERMISSIONED_DIGEST_EXPERIMENT">
                Conditional Experiment: Asynchronous Off-Chain Custody Digest Anchoring
              </option>
              <option value="VALIDATOR_QUORUM_PAUSED">
                Simulated Outage: Validator Quorum Paused (Local DB Remains Valid &amp; Unblocked)
              </option>
            </select>
          </div>

          <div className="table-scroll">
            <table className="data-table compact-table">
              <thead>
                <tr>
                  <th>Digest ID &amp; Event</th>
                  <th>Scoped Object &amp; Off-Chain Ref</th>
                  <th>Canonical Commitment Hash</th>
                  <th>Anchor Status</th>
                </tr>
              </thead>
              <tbody>
                {custodyDigests.map((dig) => (
                  <tr key={dig.digest_id}>
                    <td>
                      <strong>{dig.digest_id}</strong>
                      <div className="cell-sub">{dig.event_type}</div>
                    </td>
                    <td>
                      <code>{dig.scoped_object_ref}</code>
                      <div className="cell-sub">{dig.offchain_evidence_ref}</div>
                    </td>
                    <td>
                      <code className="font-mono">{dig.canonical_commitment_hash}</code>
                      <div className="cell-sub">Signer: {dig.signer_identity}</div>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          dig.anchor_status === 'ANCHORED_TO_SHARED_LOG'
                            ? 'badge-success'
                            : 'badge-warning'
                        }`}
                      >
                        {dig.anchor_status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* 3. Source Authority Registry & Quarantined CSV Rows */}
      <div className="two-col-grid">
        <section className="panel">
          <h3>
            <Database size={17} /> Source Authority &amp; Steward Registry (Section 6 &amp; 14)
          </h3>
          <p className="panel-subtext">
            Designates authoritative field ownership and retention policies (aligned with CERT-In 180-day ICT log retention baseline).
          </p>
          <div className="table-scroll">
            <table className="data-table compact-table">
              <thead>
                <tr>
                  <th>Source ID &amp; Name</th>
                  <th>Authoritative Fields</th>
                  <th>Owner &amp; Steward</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {sourceRegistry.map((src) => (
                  <tr key={src.source_id}>
                    <td>
                      <strong>{src.source_id}</strong>
                      <div className="cell-sub">{src.source_name}</div>
                    </td>
                    <td>
                      <code>{src.authoritative_fields.join(', ')}</code>
                      <div className="cell-sub">{src.retention_policy}</div>
                    </td>
                    <td>
                      <div>{src.owner}</div>
                      <div className="cell-sub">Steward: {src.steward}</div>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          src.validation_status === 'VERIFIED_AUTHORITATIVE'
                            ? 'badge-success'
                            : src.validation_status === 'SIMULATED_CAPTURE'
                              ? 'badge-warning'
                              : 'badge-neutral'
                        }`}
                      >
                        {src.validation_status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel">
          <h3>
            <FileWarning size={17} /> Quarantined CSV Import Rows ({quarantinedCsvRows.length})
          </h3>
          <p className="panel-subtext">
            Rejected rows from `POST /api/v1/imports/validate` are retained for custodian inspection rather than silently dropped or guessed.
          </p>
          {quarantinedCsvRows.length === 0 ? (
            <div className="empty-box">
              No quarantined CSV rows yet. Run &ldquo;1. Validate Sample CSV Batch&rdquo; in Tab 1 (Workbench) to quarantine invalid unit &amp; negative quantity rows.
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table compact-table">
                <thead>
                  <tr>
                    <th>Event Key</th>
                    <th>Raw Input</th>
                    <th>Quarantine Error Code &amp; Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {quarantinedCsvRows.map((q, idx) => (
                    <tr key={`${q.row.client_event_id}-${idx}`}>
                      <td>
                        <code>{q.row.client_event_id}</code>
                        <div className="cell-sub">{q.row.raw_source_ref}</div>
                      </td>
                      <td>
                        {q.row.raw_item_id} ({q.row.raw_batch_id}): {q.row.raw_quantity}{' '}
                        {q.row.raw_unit}
                      </td>
                      <td>
                        <span className="badge badge-danger">{q.error_code}</span>
                        <div className="cell-sub text-danger">{q.error_reason}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* 4. Append-Only Scoped Audit Sink */}
      <section className="panel">
        <h3>
          <ShieldCheck size={17} /> Scoped Append-Only Audit History (`GET /api/v1/audit` — {auditLog.length} records)
        </h3>
        <p className="panel-subtext">
          Retains actor, role, before/after version, correlation ID, reason, outcome, and hash chain for tamper evidence.
        </p>
        <div className="table-scroll">
          <table className="data-table compact-table">
            <thead>
              <tr>
                <th>Audit ID &amp; Time</th>
                <th>Actor &amp; Role</th>
                <th>Action &amp; Object</th>
                <th>Version Lineage</th>
                <th>Outcome</th>
                <th>Reason &amp; Hash Chain</th>
              </tr>
            </thead>
            <tbody>
              {auditLog.map((aud) => (
                <tr key={aud.audit_id}>
                  <td>
                    <strong>{aud.audit_id}</strong>
                    <div className="cell-sub">
                      {aud.server_time.slice(0, 19).replace('T', ' ')} UTC
                    </div>
                  </td>
                  <td>
                    <div>{aud.actor_name}</div>
                    <div className="cell-sub">
                      <code>{aud.actor_id}</code> [{aud.actor_role}]
                    </div>
                  </td>
                  <td>
                    <code>{aud.action}</code>
                    <div className="cell-sub">Ref: {aud.object_id}</div>
                  </td>
                  <td className="font-mono">
                    v{aud.before_version} → v{aud.after_version}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        aud.outcome === 'COMMITTED' ? 'badge-success' : 'badge-danger'
                      }`}
                    >
                      {aud.outcome}
                    </span>
                  </td>
                  <td>
                    <div>{aud.reason}</div>
                    <div className="cell-sub font-mono">
                      Prev: {aud.prev_hash} → Hash: {aud.entry_hash} ({aud.correlation_id})
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};
