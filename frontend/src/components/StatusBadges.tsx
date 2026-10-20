/**
 * Setu Supply (SIH26251) — Accessible Status Badges, Unit Formatters & Freshness Timers
 *
 * Enforces Section 12 Design Rules:
 * - Always show base unit beside every quantity and explicit pack conversion.
 * - Distinguish observed time, synced time, and last physical count.
 * - Always pair icon + text label + colour (never rely on red/green colour alone).
 * - Label offline drafts "Provisional — pending server validation".
 */

import React from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Clock,
  CloudOff,
  Lock,
  Package,
  ShieldAlert,
  ShieldCheck,
  Truck,
} from 'lucide-react';
import {
  BatchQualityState,
  FreshnessStatus,
  Item,
  OfflineSyncOutcome,
  RequestState,
  ShipmentState,
} from '../contracts/api';

export function formatDualUnit(qtyBase: number, item?: Item): string {
  if (!item) return `${qtyBase.toLocaleString()} units`;
  const packs = qtyBase / item.pack_size_base;
  const packFormatted = Number.isInteger(packs) ? packs.toString() : packs.toFixed(1);
  return `${qtyBase.toLocaleString()} ${item.base_unit} (${packFormatted} ${item.pack_name}${packs === 1 ? '' : 's'})`;
}

export const QuantityDisplay: React.FC<{
  qtyBase: number;
  item?: Item;
  highlight?: 'usable' | 'warning' | 'danger' | 'neutral';
  compact?: boolean;
}> = ({ qtyBase, item, highlight = 'neutral', compact = false }) => {
  if (!item) {
    return <span className="font-mono font-semibold">{qtyBase.toLocaleString()}</span>;
  }
  const packs = qtyBase / item.pack_size_base;
  const packStr = Number.isInteger(packs) ? packs.toString() : packs.toFixed(1);
  const colorClass =
    highlight === 'usable'
      ? 'qty-usable'
      : highlight === 'warning'
        ? 'qty-warning'
        : highlight === 'danger'
          ? 'qty-danger'
          : 'qty-neutral';

  return (
    <span className={`qty-pill ${colorClass}`}>
      <strong className="font-mono">
        {qtyBase.toLocaleString()} {item.base_unit}
      </strong>
      {!compact && (
        <span className="qty-subpack">
          ≈ {packStr} {item.pack_name}
          {packs === 1 ? '' : 's'} (1={item.pack_size_base} {item.base_unit})
        </span>
      )}
    </span>
  );
};

export const FreshnessBadge: React.FC<{
  status: FreshnessStatus;
  ageHours?: number;
}> = ({ status, ageHours }) => {
  if (status === 'FRESH' && (ageHours === undefined || ageHours <= 24)) {
    return (
      <span className="badge badge-success" title="Physical count and ledger sync within 24h threshold">
        <CheckCircle2 size={14} />
        <span>FRESH {ageHours !== undefined ? `(${ageHours}h old)` : ''}</span>
      </span>
    );
  }
  if (status === 'AGING' || (ageHours !== undefined && ageHours <= 48 && status !== 'STALE_GATE_ACTIVE')) {
    return (
      <span className="badge badge-warning" title="Count is between 24h and 48h old; verify soon">
        <Clock size={14} />
        <span>AGING {ageHours !== undefined ? `(${ageHours}h old)` : ''}</span>
      </span>
    );
  }
  return (
    <span className="badge badge-danger" title="Stale evidence (>48h old); approval gate requires revalidation or exception sign-off">
      <AlertOctagon size={14} />
      <span>STALE GATE ACTIVE {ageHours !== undefined ? `(${ageHours}h old)` : ''}</span>
    </span>
  );
};

export const QualityStateBadge: React.FC<{ state: BatchQualityState }> = ({ state }) => {
  switch (state) {
    case 'USABLE':
      return (
        <span className="badge badge-success">
          <CheckCircle2 size={13} />
          <span>USABLE</span>
        </span>
      );
    case 'QUARANTINED':
      return (
        <span className="badge badge-warning">
          <ShieldAlert size={13} />
          <span>QUARANTINED (HOLD)</span>
        </span>
      );
    case 'EXPIRED':
      return (
        <span className="badge badge-danger">
          <AlertOctagon size={13} />
          <span>EXPIRED (EXCLUDED)</span>
        </span>
      );
    case 'DAMAGED':
      return (
        <span className="badge badge-danger">
          <AlertTriangle size={13} />
          <span>DAMAGED (EXCLUDED)</span>
        </span>
      );
  }
};

export const RequestStateBadge: React.FC<{
  state: RequestState;
  isProvisional?: boolean;
}> = ({ state, isProvisional }) => {
  if (isProvisional) {
    return (
      <span className="badge badge-provisional">
        <CloudOff size={13} />
        <span>PROVISIONAL — PENDING SERVER VALIDATION</span>
      </span>
    );
  }
  switch (state) {
    case 'DRAFT':
      return (
        <span className="badge badge-neutral">
          <Clock size={13} />
          <span>DRAFT (READ-ONLY REC)</span>
        </span>
      );
    case 'SUBMITTED':
      return (
        <span className="badge badge-warning">
          <AlertTriangle size={13} />
          <span>SUBMITTED — AWAITING INDEPENDENT APPROVAL</span>
        </span>
      );
    case 'APPROVED':
      return (
        <span className="badge badge-success">
          <ShieldCheck size={13} />
          <span>APPROVED (INDEPENDENT AUTHORITY)</span>
        </span>
      );
    case 'REJECTED':
      return (
        <span className="badge badge-danger">
          <AlertOctagon size={13} />
          <span>REJECTED</span>
        </span>
      );
    case 'CANCELLED':
      return (
        <span className="badge badge-neutral">
          <Lock size={13} />
          <span>CANCELLED</span>
        </span>
      );
  }
};

export const ShipmentStateBadge: React.FC<{ state: ShipmentState }> = ({ state }) => {
  switch (state) {
    case 'CREATED':
      return (
        <span className="badge badge-neutral">
          <Package size={13} />
          <span>CREATED (NOT YET DISPATCHED)</span>
        </span>
      );
    case 'DISPATCH_RECORDED':
      return (
        <span className="badge badge-info">
          <Truck size={13} />
          <span>DISPATCH RECORDED (IN TRANSIT)</span>
        </span>
      );
    case 'PARTIALLY_RECEIVED':
      return (
        <span className="badge badge-warning">
          <AlertTriangle size={13} />
          <span>PARTIALLY RECEIVED (BALANCE UNRESOLVED)</span>
        </span>
      );
    case 'RECONCILED':
      return (
        <span className="badge badge-success">
          <CheckCircle2 size={13} />
          <span>RECONCILED (CLOSED)</span>
        </span>
      );
    case 'EXCEPTION_CLOSED':
      return (
        <span className="badge badge-warning">
          <ShieldAlert size={13} />
          <span>CLOSED WITH AUTHORIZED EXCEPTION</span>
        </span>
      );
  }
};

export const OfflineSyncBadge: React.FC<{ status: OfflineSyncOutcome }> = ({ status }) => {
  switch (status) {
    case 'PENDING':
      return (
        <span className="badge badge-provisional">
          <CloudOff size={13} />
          <span>PROVISIONAL — PENDING SERVER VALIDATION</span>
        </span>
      );
    case 'ACCEPTED':
      return (
        <span className="badge badge-success">
          <CheckCircle2 size={13} />
          <span>SYNC ACCEPTED</span>
        </span>
      );
    case 'CONFLICT':
      return (
        <span className="badge badge-danger">
          <AlertOctagon size={13} />
          <span>VERSION CONFLICT (REQUIRES REVIEW)</span>
        </span>
      );
    case 'REJECTED':
      return (
        <span className="badge badge-danger">
          <AlertTriangle size={13} />
          <span>SYNC REJECTED</span>
        </span>
      );
  }
};

export const TimestampTrioBar: React.FC<{
  observedAt: string;
  syncedAt: string;
  lastPhysicalCountAt: string;
  observationAgeHours: number;
  isStale: boolean;
}> = ({ observedAt, syncedAt, lastPhysicalCountAt, observationAgeHours, isStale }) => {
  return (
    <div className={`timestamp-trio ${isStale ? 'timestamp-trio-stale' : ''}`}>
      <div className="ts-item">
        <span className="ts-label">Observed (As-Of):</span>
        <code className="ts-val">{observedAt.replace('T', ' ').slice(0, 16)} UTC</code>
      </div>
      <div className="ts-item">
        <span className="ts-label">Last Server Sync:</span>
        <code className="ts-val">{syncedAt.replace('T', ' ').slice(0, 16)} UTC</code>
      </div>
      <div className="ts-item">
        <span className="ts-label">Last Physical Count:</span>
        <code className="ts-val">
          {lastPhysicalCountAt.replace('T', ' ').slice(0, 16)} UTC ({observationAgeHours}h ago)
        </code>
      </div>
      <FreshnessBadge
        status={isStale ? 'STALE_GATE_ACTIVE' : observationAgeHours > 24 ? 'AGING' : 'FRESH'}
        ageHours={observationAgeHours}
      />
    </div>
  );
};
