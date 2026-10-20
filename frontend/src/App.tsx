/**
 * Setu Supply (SIH26251) — Main Application Shell (Person 3: UI / Device Owner)
 *
 * Connects:
 * - TopControlBar (Identity/Compartment switcher, Online/Offline/Expired-Lease toggle, Sync Queue)
 * - DemoWalkthroughBar (Section 20 Three-Minute Demo Video Script)
 * - 5 Principal Operational Views:
 *   1. WORKBENCH        — Exceptions, Authoritative Stock Matrix, Batch QA & CSV Import
 *   2. IOT_GATEWAY      — IoT Capture Adapter, Device Registry, Sequence/Replay & Cold-Chain
 *   3. FORECAST_GIS     — 180-Day Forecast (120/30/30), Constrained GIS Graph Planner & Policy Engine
 *   4. APPROVAL_RECEIPT — Independent Approval (Creator != Approver), Atomic Reserve & Partial Receipt
 *   5. OFFLINE_AUDIT    — IndexedDB Sync Conflict Resolver, Audit Sink, Optional Local Assistant & Custody Digests
 * - Expired Offline Authority Lease Fallback (Section 12: hides cached records and presents Blank Minimal Evidence Form)
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertOctagon,
  Barcode,
  CheckCircle2,
  ClipboardList,
  CloudOff,
  Compass,
  KeyRound,
  Layers,
  ShieldAlert,
  Truck,
  X,
} from 'lucide-react';
import {
  ApiErrorEnvelope,
  AuthenticatedPersona,
  OfflineEvidenceItem,
} from './contracts/api';
import { ITEMS, PERSONAS, SITES } from './data/syntheticFixtures';
import {
  enqueueOfflineEvidence,
  listOfflineEvidenceQueue,
} from './services/indexedDbQueue';
import {
  NetworkConnectivityMode,
  setuApiClient,
} from './services/apiClient';
import {
  computeNeedsActionTasks,
  resetEngineStateToSeed,
} from './services/mockContractEngine';
import { TopControlBar } from './components/TopControlBar';
import {
  ActiveTabId,
  DemoWalkthroughBar,
} from './components/DemoWalkthroughBar';
import { AcceptanceTestSuiteModal } from './components/AcceptanceTestSuiteModal';
import { WorkbenchOverviewView } from './views/WorkbenchOverviewView';
import { IoTCaptureGatewayView } from './views/IoTCaptureGatewayView';
import { ForecastAndGisPlannerView } from './views/ForecastAndGisPlannerView';
import { ApprovalFulfilmentView } from './views/ApprovalFulfilmentView';
import { OfflineSyncAndExtensionsView } from './views/OfflineSyncAndExtensionsView';

export const App: React.FC = () => {
  const [activePersona, setActivePersona] = useState<AuthenticatedPersona>(
    PERSONAS[0]
  );
  const [selectedSiteId, setSelectedSiteId] = useState<string>('SITE-NORTH-01');
  const [networkMode, setNetworkMode] =
    useState<NetworkConnectivityMode>('ONLINE');
  const [activeTab, setActiveTab] = useState<ActiveTabId>('WORKBENCH');
  const [focusedItemId, setFocusedItemId] = useState<string>('ITM-RATION-MRE');
  const [isAcceptanceOpen, setIsAcceptanceOpen] = useState<boolean>(false);

  const [inventoryData, setInventoryData] = useState<
    Awaited<ReturnType<typeof setuApiClient.getInventory>> | null
  >(null);
  const [auditData, setAuditData] = useState<
    Awaited<ReturnType<typeof setuApiClient.getAuditAndQuality>> | null
  >(null);
  const [offlineQueue, setOfflineQueue] = useState<OfflineEvidenceItem[]>([]);
  const [scopeDenialError, setScopeDenialError] =
    useState<ApiErrorEnvelope | null>(null);

  const [toast, setToast] = useState<{
    message: string;
    tone: 'success' | 'error' | 'info';
  } | null>(null);

  // Blank minimal supervised evidence form state (used when cached offline authority expires — Section 12)
  const [blankItemRef, setBlankItemRef] = useState<string>('ITM-RATION-MRE');
  const [blankBatchRef, setBlankBatchRef] = useState<string>('BCH-MRE-2026-B1');
  const [blankQtyBase, setBlankQtyBase] = useState<number>(48);
  const [blankNote, setBlankNote] = useState<string>(
    'Emergency manual tally recorded during prolonged link loss after session lease expiry'
  );

  const notify = useCallback(
    (message: string, tone: 'success' | 'error' | 'info' = 'info') => {
      setToast({ message, tone });
    },
    []
  );

  const refreshAll = useCallback(async () => {
    const q = await listOfflineEvidenceQueue();
    setOfflineQueue(q);

    try {
      const inv = await setuApiClient.getInventory(
        activePersona,
        selectedSiteId
      );
      const aud = await setuApiClient.getAuditAndQuality(
        activePersona,
        selectedSiteId
      );
      setInventoryData(inv);
      setAuditData(aud);
      setScopeDenialError(null);
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      setScopeDenialError(apiErr);
      setInventoryData(null);
    }
  }, [activePersona, selectedSiteId]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const handleChangeNetworkMode = (mode: NetworkConnectivityMode) => {
    setuApiClient.setNetworkMode(mode);
    setNetworkMode(mode);
    if (mode === 'ONLINE') {
      notify(
        'Connected to server: Central atomic validation and policy enforcement active.',
        'success'
      );
    } else if (mode === 'OFFLINE_CACHED_AUTH') {
      notify(
        'Offline Mode Active: Showing cached snapshot timestamp. Shared reservations and approvals are prohibited; drafts & receipts queue provisionally in IndexedDB.',
        'info'
      );
    } else {
      notify(
        'Offline Authority Lease Expired (Section 12): Protected cached records hidden. Only Blank Supervised Evidence Capture is available.',
        'error'
      );
    }
  };

  const handleSyncNow = async () => {
    if (networkMode !== 'ONLINE') {
      setuApiClient.setNetworkMode('ONLINE');
      setNetworkMode('ONLINE');
    }
    try {
      const res = await setuApiClient.syncOfflineEvidence(activePersona, false);
      await refreshAll();
      notify(
        `Synced Offline Queue: ${res.response.accepted_count} accepted, ${res.response.conflict_count} conflict(s), ${res.response.rejected_count} rejected.`,
        res.response.conflict_count > 0 ? 'info' : 'success'
      );
      if (res.response.conflict_count > 0) {
        setActiveTab('OFFLINE_AUDIT');
      }
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      notify(apiErr.message || 'Sync failed', 'error');
    }
  };

  const handleResetSeed = async () => {
    resetEngineStateToSeed();
    setuApiClient.setNetworkMode('ONLINE');
    setNetworkMode('ONLINE');
    await refreshAll();
    notify(
      'Reset authoritative state to initial synthetic seed (4 fictional sites, 6 items, 180-day series).',
      'info'
    );
  };

  const handleCaptureBlankSupervisedEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    const item: OfflineEvidenceItem = {
      queue_id: `Q-SUP-${Date.now().toString(36).toUpperCase()}`,
      client_event_id: `CEV-EXPIRED-LEASE-${Date.now().toString(36).slice(-4).toUpperCase()}`,
      kind: 'SUPERVISED_BLANK_EVIDENCE',
      site_id: selectedSiteId,
      item_id: blankItemRef,
      created_by: activePersona.user_id,
      created_by_role: activePersona.role,
      created_at_local: new Date().toISOString(),
      expected_version: 0,
      payload: {
        batch_id: blankBatchRef,
        quantity_base: blankQtyBase,
        reason: blankNote,
      },
      summary_text: `[Expired Lease Blank Form] ${blankItemRef} (${blankBatchRef}): ${blankQtyBase} base units — ${blankNote}`,
      status: 'PENDING',
      authority_expired_capture: true,
    };
    await enqueueOfflineEvidence(item);
    await refreshAll();
    notify(
      `Saved Blank Supervised Evidence (${item.client_event_id}) to local queue. Will require Custodian review upon reconnect.`,
      'info'
    );
  };

  const pendingOfflineCount = offlineQueue.filter(
    (q) => q.status === 'PENDING'
  ).length;
  const conflictOfflineCount = offlineQueue.filter(
    (q) => q.status === 'CONFLICT'
  ).length;

  const needsAction = inventoryData
    ? computeNeedsActionTasks(activePersona, selectedSiteId, offlineQueue)
    : [];

  return (
    <div className="app-shell">
      <TopControlBar
        personas={PERSONAS}
        activePersona={activePersona}
        onSelectPersona={(p) => {
          setActivePersona(p);
          notify(`Switched authenticated identity to ${p.display_name} [${p.role}].`, 'info');
        }}
        sites={SITES}
        selectedSiteId={selectedSiteId}
        onSelectSiteId={(sId) => setSelectedSiteId(sId)}
        networkMode={networkMode}
        onChangeNetworkMode={handleChangeNetworkMode}
        pendingOfflineCount={pendingOfflineCount}
        conflictOfflineCount={conflictOfflineCount}
        onSyncNow={handleSyncNow}
        onResetSeed={handleResetSeed}
        onOpenAcceptanceSuite={() => setIsAcceptanceOpen(true)}
        snapshotVersion={inventoryData?.snapshot.version ?? 0}
      />

      {/* Section 20 Three-Minute Demo Video Script Bar */}
      <DemoWalkthroughBar
        activeTab={activeTab}
        onSelectTab={(tab) => setActiveTab(tab)}
      />

      {/* Toast Notification Banner */}
      {toast && (
        <div className={`toast-banner toast-${toast.tone}`} role="status">
          <div className="toast-content">
            {toast.tone === 'success' && <CheckCircle2 size={16} />}
            {toast.tone === 'error' && <AlertOctagon size={16} />}
            {toast.tone === 'info' && <ShieldAlert size={16} />}
            <span>{toast.message}</span>
          </div>
          <button
            type="button"
            className="btn-icon"
            onClick={() => setToast(null)}
            aria-label="Dismiss notification"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {/* Offline Cached Snapshot Warning Banner */}
      {networkMode === 'OFFLINE_CACHED_AUTH' && inventoryData && (
        <div className="offline-banner">
          <CloudOff size={16} />
          <span>
            <strong>DISCONNECTED — SHOWING LAST VERIFIED SNAPSHOT ({inventoryData.snapshot.snapshot_id} as of {inventoryData.snapshot.as_of_time.slice(0, 16).replace('T', ' ')} UTC):</strong>{' '}
            All drafts, counts, and receipt parts submitted now are labelled{' '}
            <em>&ldquo;Provisional — pending server validation&rdquo;</em>. Shared-stock reservations and approvals are disabled while offline.
          </span>
        </div>
      )}

      {/* Navigation Tabs */}
      <nav className="main-tabs" aria-label="Primary Operational Modules">
        <button
          type="button"
          className={`tab-btn ${activeTab === 'WORKBENCH' ? 'tab-btn-active' : ''}`}
          onClick={() => setActiveTab('WORKBENCH')}
        >
          <Layers size={15} />
          <span>1. Workbench &amp; Stock Authority</span>
          {needsAction.length > 0 && (
            <span className="tab-count">{needsAction.length}</span>
          )}
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'IOT_GATEWAY' ? 'tab-btn-active' : ''}`}
          onClick={() => setActiveTab('IOT_GATEWAY')}
        >
          <Barcode size={15} />
          <span>2. IoT Capture &amp; Gateway Controls</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'FORECAST_GIS' ? 'tab-btn-active' : ''}`}
          onClick={() => setActiveTab('FORECAST_GIS')}
        >
          <Compass size={15} />
          <span>3. 180d Forecast, GIS Planner &amp; Policy</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'APPROVAL_RECEIPT' ? 'tab-btn-active' : ''}`}
          onClick={() => setActiveTab('APPROVAL_RECEIPT')}
        >
          <Truck size={15} />
          <span>4. Independent Approval &amp; Receipt</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'OFFLINE_AUDIT' ? 'tab-btn-active' : ''}`}
          onClick={() => setActiveTab('OFFLINE_AUDIT')}
        >
          <ClipboardList size={15} />
          <span>5. Offline Sync, Audit &amp; Extensions</span>
          {(pendingOfflineCount > 0 || conflictOfflineCount > 0) && (
            <span className="tab-count">
              {pendingOfflineCount + conflictOfflineCount}
            </span>
          )}
        </button>
      </nav>

      {/* Main Content Container */}
      <main className="main-content">
        {/* Case 1: Section 12 Expired Offline Authority Lease -> Hide cached records & show Blank Minimal Evidence Form */}
        {networkMode === 'OFFLINE_AUTHORITY_EXPIRED' ? (
          <section className="panel panel-danger-border">
            <div className="panel-header-row">
              <div>
                <div className="eyebrow text-danger">
                  <KeyRound size={15} /> SECTION 12 SECURITY CONTROL — CACHED OFFLINE AUTHORIZATION LEASE EXPIRED
                </div>
                <h2>Protected Cached Site Records Hidden • Supervised Blank Evidence Capture Only</h2>
                <p className="panel-subtext">
                  Per Section 12: <em>&ldquo;After cached authorization expires, do not keep showing protected cached records. A blank minimal evidence form may support supervised later reconciliation if approved.&rdquo;</em>
                </p>
              </div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handleChangeNetworkMode('ONLINE')}
              >
                Reconnect &amp; Re-Authenticate Session
              </button>
            </div>

            <form
              onSubmit={handleCaptureBlankSupervisedEvidence}
              className="compact-form"
              style={{ marginTop: '1rem' }}
            >
              <div className="form-row-4">
                <div>
                  <label className="form-label">Item Code Reference</label>
                  <select
                    className="form-select"
                    value={blankItemRef}
                    onChange={(e) => setBlankItemRef(e.target.value)}
                  >
                    {ITEMS.map((it) => (
                      <option key={it.item_id} value={it.item_id}>
                        {it.item_id} ({it.base_unit})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="form-label">Physical Batch Label</label>
                  <input
                    type="text"
                    className="form-input"
                    value={blankBatchRef}
                    onChange={(e) => setBlankBatchRef(e.target.value)}
                  />
                </div>
                <div>
                  <label className="form-label">Observed Quantity (Base Units)</label>
                  <input
                    type="number"
                    className="form-input"
                    value={blankQtyBase}
                    onChange={(e) => setBlankQtyBase(Number(e.target.value))}
                  />
                </div>
                <div>
                  <label className="form-label">Witness / Tally Note</label>
                  <input
                    type="text"
                    className="form-input"
                    value={blankNote}
                    onChange={(e) => setBlankNote(e.target.value)}
                  />
                </div>
              </div>
              <div style={{ marginTop: '0.75rem' }}>
                <button type="submit" className="btn btn-warning">
                  Queue Blank Supervised Evidence for Custodian Reconciliation
                </button>
              </div>
            </form>
          </section>
        ) : scopeDenialError ? (
          /* Case 2: Acceptance Scenario 3 -> Cross-Site Compartment Denial (403) */
          <section className="panel panel-danger-border">
            <div className="panel-header-row">
              <div>
                <div className="eyebrow text-danger">
                  <AlertOctagon size={15} /> ACCEPTANCE SCENARIO 3 VERIFIED — COMPARTMENT SCOPE DENIED ({scopeDenialError.http_status})
                </div>
                <h2>{scopeDenialError.code}</h2>
                <p className="panel-subtext">{scopeDenialError.message}</p>
                <p className="cell-sub">
                  Correlation ID: <code>{scopeDenialError.correlation_id}</code> • Zero inaccessible site records were leaked in the error response, and the denial was recorded in the append-only audit sink.
                </p>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => setSelectedSiteId(activePersona.default_site_id)}
                >
                  Return to Authorized Site ({activePersona.default_site_id})
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    const cust = PERSONAS.find((p) => p.role === 'DATA_CUSTODIAN');
                    if (cust) setActivePersona(cust);
                  }}
                >
                  Switch to All-Site Data Custodian
                </button>
              </div>
            </div>
          </section>
        ) : (
          /* Case 3: Normal Authorized Views */
          inventoryData &&
          auditData && (
            <>
              {activeTab === 'WORKBENCH' && (
                <WorkbenchOverviewView
                  persona={activePersona}
                  site={inventoryData.site}
                  snapshot={inventoryData.snapshot}
                  items={inventoryData.items}
                  projections={inventoryData.projections}
                  batches={inventoryData.batches}
                  events={inventoryData.events}
                  needsAction={needsAction}
                  onNavigateTab={(tab, itemId) => {
                    if (itemId) setFocusedItemId(itemId);
                    setActiveTab(tab);
                  }}
                  onRefreshState={refreshAll}
                  onNotify={notify}
                />
              )}

              {activeTab === 'IOT_GATEWAY' && (
                <IoTCaptureGatewayView
                  persona={activePersona}
                  site={inventoryData.site}
                  items={inventoryData.items}
                  batches={inventoryData.batches}
                  devices={inventoryData.iot_devices}
                  observations={inventoryData.iot_observations}
                  onRefreshState={refreshAll}
                  onNotify={notify}
                />
              )}

              {activeTab === 'FORECAST_GIS' && (
                <ForecastAndGisPlannerView
                  persona={activePersona}
                  site={inventoryData.site}
                  items={inventoryData.items}
                  initialItemId={focusedItemId}
                  onNavigateTab={(tab) => setActiveTab(tab)}
                  onRefreshState={refreshAll}
                  onNotify={notify}
                />
              )}

              {activeTab === 'APPROVAL_RECEIPT' && (
                <ApprovalFulfilmentView
                  persona={activePersona}
                  site={inventoryData.site}
                  snapshot={inventoryData.snapshot}
                  items={inventoryData.items}
                  projections={inventoryData.projections}
                  onRefreshState={refreshAll}
                  onNotify={notify}
                />
              )}

              {activeTab === 'OFFLINE_AUDIT' && (
                <OfflineSyncAndExtensionsView
                  persona={activePersona}
                  site={inventoryData.site}
                  snapshot={inventoryData.snapshot}
                  offlineQueue={offlineQueue}
                  auditLog={auditData.audit_log}
                  sourceRegistry={auditData.source_registry}
                  quarantinedCsvRows={auditData.quarantined_csv_rows}
                  custodyDigests={auditData.custody_digests}
                  onRefreshState={refreshAll}
                  onNotify={notify}
                />
              )}
            </>
          )
        )}
      </main>

      {isAcceptanceOpen && (
        <AcceptanceTestSuiteModal
          onClose={() => setIsAcceptanceOpen(false)}
          onCompleteRefresh={refreshAll}
        />
      )}
    </div>
  );
};
