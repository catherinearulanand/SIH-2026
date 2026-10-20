/**
 * Setu Supply (SIH26251) — Top Operational Control Bar
 *
 * Provides:
 * - Authenticated Identity & Scoped Policy Switcher (for testing Invariant 6, 7, 11)
 * - Fictional Site Selector (including out-of-scope test trigger for Acceptance Test 4)
 * - Network Connectivity & Offline Authority Lease Switcher (ONLINE / OFFLINE / LEASE EXPIRED)
 * - One-click Offline Queue Replay (POST /api/v1/sync)
 * - Reset Demo State button
 */

import React from 'react';
import {
  ClipboardCheck,
  CloudOff,
  Database,
  KeyRound,
  RefreshCw,
  RotateCcw,
  Shield,
  UserCheck,
  Wifi,
} from 'lucide-react';
import { AuthenticatedPersona, Site } from '../contracts/api';
import { NetworkConnectivityMode } from '../services/apiClient';

interface TopControlBarProps {
  personas: AuthenticatedPersona[];
  activePersona: AuthenticatedPersona;
  onSelectPersona: (p: AuthenticatedPersona) => void;
  sites: Site[];
  selectedSiteId: string;
  onSelectSiteId: (siteId: string) => void;
  networkMode: NetworkConnectivityMode;
  onChangeNetworkMode: (mode: NetworkConnectivityMode) => void;
  pendingOfflineCount: number;
  conflictOfflineCount: number;
  onSyncNow: () => void;
  onResetSeed: () => void;
  onOpenAcceptanceSuite: () => void;
  snapshotVersion: number;
}

export const TopControlBar: React.FC<TopControlBarProps> = ({
  personas,
  activePersona,
  onSelectPersona,
  sites,
  selectedSiteId,
  onSelectSiteId,
  networkMode,
  onChangeNetworkMode,
  pendingOfflineCount,
  conflictOfflineCount,
  onSyncNow,
  onResetSeed,
  onOpenAcceptanceSuite,
  snapshotVersion,
}) => {
  return (
    <header className="top-header">
      <div className="brand-row">
        <div className="brand-title-group">
          <div className="brand-emblem">
            <Shield size={20} />
          </div>
          <div>
            <div className="brand-headline">
              <h1>SETU SUPPLY</h1>
              <span className="sih-tag">SIH26251 • Predictive Logistics &amp; Supply Assurance</span>
              <span className="version-chip" title="Authoritative site ledger version">
                <Database size={12} />
                Ledger v{snapshotVersion}
              </span>
            </div>
            <p className="brand-subtitle">
              Deterministic Inventory Authority • Uncertainty-Aware Replenishment • Independent Approval &amp; Reconciliation
            </p>
          </div>
        </div>

        <div className="control-strip">
          {/* Authenticated Identity / Role Switcher */}
          <div className="control-box">
            <label htmlFor="persona-select" className="control-label">
              <UserCheck size={13} /> Authenticated Identity &amp; Role Scope
            </label>
            <select
              id="persona-select"
              className="control-select"
              value={activePersona.user_id}
              onChange={(e) => {
                const found = personas.find((p) => p.user_id === e.target.value);
                if (found) onSelectPersona(found);
              }}
            >
              {personas.map((p) => (
                <option key={p.user_id} value={p.user_id}>
                  {p.display_name} [{p.role}] — Scope: {p.allowed_site_ids.join(', ')}
                </option>
              ))}
            </select>
          </div>

          {/* Fictional Site Selector (Allows testing cross-site 403 denial!) */}
          <div className="control-box">
            <label htmlFor="site-select" className="control-label">
              <Database size={13} /> Target Fictional Site (Test Scope Check)
            </label>
            <select
              id="site-select"
              className="control-select"
              value={selectedSiteId}
              onChange={(e) => onSelectSiteId(e.target.value)}
            >
              {sites.map((s) => {
                const allowed = activePersona.allowed_site_ids.includes(s.site_id);
                return (
                  <option key={s.site_id} value={s.site_id}>
                    {s.site_id} — {s.sector_label} {allowed ? '(In Scope)' : '🔒 (Out of Scope -> Test 403)'}
                  </option>
                );
              })}
            </select>
          </div>

          {/* Network & Offline Authority Lease Mode */}
          <div className="control-box">
            <label htmlFor="network-select" className="control-label">
              {networkMode === 'ONLINE' ? (
                <Wifi size={13} />
              ) : networkMode === 'OFFLINE_CACHED_AUTH' ? (
                <CloudOff size={13} />
              ) : (
                <KeyRound size={13} />
              )}{' '}
              Connectivity &amp; Lease State
            </label>
            <select
              id="network-select"
              className={`control-select network-select-${networkMode.toLowerCase()}`}
              value={networkMode}
              onChange={(e) => onChangeNetworkMode(e.target.value as NetworkConnectivityMode)}
            >
              <option value="ONLINE">🟢 ONLINE — Central Atomic Validation</option>
              <option value="OFFLINE_CACHED_AUTH">
                🟠 OFFLINE — Cached Snapshot &amp; Provisional Queue
              </option>
              <option value="OFFLINE_AUTHORITY_EXPIRED">
                🔴 OFFLINE (LEASE EXPIRED) — Blank Supervised Capture Only
              </option>
            </select>
          </div>

          <div className="control-actions">
            <button
              type="button"
              className="btn btn-success"
              onClick={onOpenAcceptanceSuite}
              title="Execute all 15 Section 17 Critical Acceptance Scenarios end-to-end"
            >
              <ClipboardCheck size={14} />
              <span>Verify 15 Scenarios</span>
            </button>
            <button
              type="button"
              className={`btn ${pendingOfflineCount > 0 ? 'btn-primary' : 'btn-secondary'}`}
              onClick={onSyncNow}
              title="Replay queued provisional evidence via POST /api/v1/sync"
            >
              <RefreshCw size={14} />
              <span>
                Sync Queue ({pendingOfflineCount} pending
                {conflictOfflineCount > 0 ? `, ${conflictOfflineCount} conflict` : ''})
              </span>
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onResetSeed}
              title="Reset localStorage & IndexedDB state to initial synthetic seed for clean demo rehearsal"
            >
              <RotateCcw size={14} />
              <span>Reset Seed</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
