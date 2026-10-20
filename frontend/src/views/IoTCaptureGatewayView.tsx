/**
 * Setu Supply (SIH26251) — Tab 2: IoT Capture Adapter, Gateway Buffer & Physical-Truth Controls (Section 8 & 11)
 * Role: Person 3 — UI / Device Owner
 */

import React, { useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  Barcode,
  CheckCircle2,
  Cpu,
  Radio,
  ShieldAlert,
  Thermometer,
} from 'lucide-react';
import {
  ApiErrorEnvelope,
  AuthenticatedPersona,
  Batch,
  IoTObservation,
  IoTObservationType,
  Item,
  RegisteredIoTDevice,
  Site,
} from '../contracts/api';
import { setuApiClient } from '../services/apiClient';

interface IoTCaptureGatewayViewProps {
  persona: AuthenticatedPersona;
  site: Site;
  items: Item[];
  batches: Batch[];
  devices: RegisteredIoTDevice[];
  observations: IoTObservation[];
  onRefreshState: () => void;
  onNotify: (msg: string, tone: 'success' | 'error' | 'info') => void;
}

export const IoTCaptureGatewayView: React.FC<IoTCaptureGatewayViewProps> = ({
  persona,
  site,
  items,
  batches,
  devices,
  observations,
  onRefreshState,
  onNotify,
}) => {
  const [selectedObs, setSelectedObs] = useState<IoTObservation | null>(
    observations[0] ?? null
  );
  const [deviceId, setDeviceId] = useState<string>(
    devices[0]?.device_id ?? 'scanner-demo-01'
  );
  const [obsType, setObsType] = useState<IoTObservationType>('barcode_seen');
  const [batchId, setBatchId] = useState<string>(
    batches[0]?.batch_id ?? 'BCH-MRE-2026-B1'
  );
  const [valueNum, setValueNum] = useState<number>(2);
  const [unitStr, setUnitStr] = useState<string>('Crate');
  const [customSequence, setCustomSequence] = useState<number>(
    (devices[0]?.last_sequence ?? 42) + 1
  );
  const [promoteType, setPromoteType] = useState<'RECEIPT' | 'ISSUE'>('RECEIPT');

  const activeDevice = devices.find((d) => d.device_id === deviceId) ?? devices[0];
  const targetBatch = batches.find((b) => b.batch_id === batchId) ?? batches[0];

  const handleIngestObservation = async (overrideParams?: {
    event_id?: string;
    device_id?: string;
    boot_session?: string;
    sequence?: number;
    item_id?: string;
    batch_id?: string;
    observation_type?: IoTObservationType;
    value?: number;
    unit?: string;
  }) => {
    const dev =
      devices.find((d) => d.device_id === (overrideParams?.device_id ?? deviceId)) ??
      activeDevice;
    const bch =
      batches.find((b) => b.batch_id === (overrideParams?.batch_id ?? batchId)) ??
      targetBatch;
    if (!dev || !bch) return;

    const seqToSend = overrideParams?.sequence ?? customSequence;
    const evtId =
      overrideParams?.event_id ??
      `evt-demo-${String(seqToSend).padStart(5, '0')}-${Date.now().toString(36).slice(-3)}`;

    try {
      const res = await setuApiClient.postIoTObservation(persona, {
        event_id: evtId,
        device_id: dev.device_id,
        boot_session: overrideParams?.boot_session ?? dev.boot_session,
        sequence: seqToSend,
        site_id: site.site_id,
        item_id: overrideParams?.item_id ?? bch.item_id,
        batch_id: bch.batch_id,
        observation_type: overrideParams?.observation_type ?? obsType,
        value: overrideParams?.value ?? valueNum,
        unit: overrideParams?.unit ?? unitStr,
      });

      onRefreshState();
      if (res.queued_offline) {
        onNotify(
          `Link Loss Store-and-Forward (Section 8 Rule 6): Buffered ${res.queued_offline.client_event_id} in IndexedDB queue.`,
          'info'
        );
      } else if (res.duplicate_ignored && res.observation) {
        setSelectedObs(res.observation);
        onNotify(
          `Duplicate Replay Ignored (Scenario 12): Sequence ${seqToSend} on ${dev.boot_session} already ingested. Zero stock effect.`,
          'info'
        );
      } else if (res.observation) {
        setSelectedObs(res.observation);
        setCustomSequence(seqToSend + 1);
        if (res.observation.status === 'QUARANTINED_ANOMALY') {
          onNotify(
            `IoT Gateway Quarantined (${res.observation.event_id}): ${res.observation.anomaly_flags[0]}`,
            'error'
          );
        } else {
          onNotify(
            `Ingested Provisional Observation ${res.observation.event_id} (seq=${res.observation.sequence}). Stock unchanged until promoted to an authorized business event.`,
            'success'
          );
        }
      }
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Gateway rejected observation', 'error');
    }
  };

  const handlePromoteSelected = async () => {
    if (!selectedObs) return;
    try {
      const evt = await setuApiClient.promoteObservationToLedger(
        persona,
        selectedObs.event_id,
        promoteType,
        `Storekeeper verified physical condition & linked observation ${selectedObs.event_id}`
      );
      onRefreshState();
      onNotify(
        `Promoted observation ${selectedObs.event_id} -> Authorized Ledger Event ${evt.event_id} (${evt.type}: ${evt.quantity_base} base units).`,
        'success'
      );
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Cannot promote observation', 'error');
    }
  };

  return (
    <div className="view-stack">
      {/* Banner explaining Section 8 Physical-Truth Controls */}
      <section className="panel panel-highlight">
        <div className="panel-header-row">
          <div>
            <div className="eyebrow">
              <Radio size={14} /> SECTION 8 &amp; 11 — IOT CAPTURE ADAPTER &amp; GATEWAY PHYSICAL-TRUTH CONTROLS (SIMULATED STREAM)
            </div>
            <h2>Authenticated Gateway Ingestion • Monotonic Sequence • Store-and-Forward Buffer</h2>
            <p className="panel-subtext">
              <strong>Core Rule (Section 8):</strong> A barcode scan or RFID pass identifies an object; it does <em>not</em> alone prove count, quality, or custody transfer. Repeated RFID reads are observations, not repeated receipts. Only an authorized business event mutates stock.
            </p>
          </div>
          <span className="badge badge-warning">
            <Cpu size={13} />
            <span>LABELLED HARDWARE SIMULATOR (SECTION 3 &amp; 8)</span>
          </span>
        </div>

        {/* One-Click Physical-Truth & Anomaly Test Presets (Scenario 12) */}
        <div className="preset-strip">
          <span className="preset-label">Scenario 12 One-Click Injectors:</span>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() =>
              handleIngestObservation({
                device_id: 'scanner-demo-01',
                batch_id: 'BCH-MRE-2026-B1',
                observation_type: 'barcode_seen',
                value: 2,
                unit: 'Crate',
                sequence: (devices.find((d) => d.device_id === 'scanner-demo-01')?.last_sequence ?? 42) + 1,
              })
            }
          >
            <Barcode size={13} />
            <span>1. Valid Barcode Scan (+Seq)</span>
          </button>

          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={() =>
              handleIngestObservation({
                event_id: 'evt-demo-00042',
                device_id: 'scanner-demo-01',
                boot_session: 'boot-demo-03',
                sequence: 42,
                batch_id: 'BCH-MRE-2026-B1',
                observation_type: 'barcode_seen',
                value: 1,
                unit: 'Crate',
              })
            }
          >
            <span>2. Replay Duplicate evt-demo-00042 (Seq 42)</span>
          </button>

          <button
            type="button"
            className="btn btn-sm btn-warning"
            onClick={() =>
              handleIngestObservation({
                device_id: 'scanner-demo-01',
                batch_id: 'BCH-MRE-2026-B1',
                observation_type: 'barcode_seen',
                value: 1,
                unit: 'Crate',
                sequence: (devices.find((d) => d.device_id === 'scanner-demo-01')?.last_sequence ?? 42) + 6,
              })
            }
          >
            <AlertTriangle size={13} />
            <span>3. Inject Sequence Gap (+6 Jump)</span>
          </button>

          <button
            type="button"
            className="btn btn-sm btn-warning"
            onClick={() =>
              handleIngestObservation({
                device_id: 'coldchain-sensor-02',
                batch_id: 'BCH-ORS-2026-QUAR',
                observation_type: 'coldchain_temp_c',
                value: 31.8,
                unit: 'CELSIUS',
                sequence: (devices.find((d) => d.device_id === 'coldchain-sensor-02')?.last_sequence ?? 108) + 1,
              })
            }
          >
            <Thermometer size={13} />
            <span>4. Cold-Chain Excursion (31.8°C)</span>
          </button>

          <button
            type="button"
            className="btn btn-sm btn-danger"
            onClick={() =>
              handleIngestObservation({
                device_id: 'coldchain-sensor-02',
                batch_id: 'BCH-ORS-2026-QUAR',
                observation_type: 'coldchain_temp_c',
                value: 96.5,
                unit: 'CELSIUS',
                sequence: (devices.find((d) => d.device_id === 'coldchain-sensor-02')?.last_sequence ?? 108) + 1,
              })
            }
          >
            <AlertOctagon size={13} />
            <span>5. Implausible / Spoofed Probe (96.5°C)</span>
          </button>
        </div>
      </section>

      <div className="two-col-grid">
        {/* Left: Registered Device Provisioning Table + Custom Simulator Form */}
        <section className="panel">
          <h3>
            <Cpu size={17} /> Provisioned Edge Devices &amp; Gateway Bindings
          </h3>
          <p className="panel-subtext">
            Devices are bound to a single site compartment and authenticated via gateway HMAC. Uncalibrated sensors are automatically quarantined.
          </p>

          <div className="table-scroll">
            <table className="data-table compact-table">
              <thead>
                <tr>
                  <th>Device ID &amp; Type</th>
                  <th>Gateway &amp; Site Scope</th>
                  <th>Boot Session / Last Seq</th>
                  <th>Calibration Status</th>
                </tr>
              </thead>
              <tbody>
                {devices.map((dev) => (
                  <tr key={dev.device_id}>
                    <td>
                      <strong>{dev.device_id}</strong>
                      <div className="cell-sub">{dev.device_name}</div>
                    </td>
                    <td>
                      <code>{dev.gateway_id}</code>
                      <div className="cell-sub">Bound: {dev.assigned_site_id}</div>
                    </td>
                    <td>
                      <code>{dev.boot_session}</code>
                      <div className="cell-sub">Seq: #{dev.last_sequence}</div>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          dev.calibration_status === 'CALIBRATED'
                            ? 'badge-success'
                            : 'badge-danger'
                        }`}
                      >
                        {dev.calibration_status}
                      </span>
                      <div className="cell-sub">Due: {dev.calibration_due_date}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <hr className="divider" />

          <h4>Custom Device Observation Transmitter (`POST /api/v1/observations`)</h4>
          <div className="compact-form">
            <div className="form-row-3">
              <div>
                <label className="form-label">Device</label>
                <select
                  className="form-select"
                  value={deviceId}
                  onChange={(e) => {
                    setDeviceId(e.target.value);
                    const d = devices.find((x) => x.device_id === e.target.value);
                    if (d) setCustomSequence(d.last_sequence + 1);
                  }}
                >
                  {devices.map((d) => (
                    <option key={d.device_id} value={d.device_id}>
                      {d.device_id} ({d.device_type})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="form-label">Observation Type</label>
                <select
                  className="form-select"
                  value={obsType}
                  onChange={(e) => setObsType(e.target.value as IoTObservationType)}
                >
                  <option value="barcode_seen">barcode_seen</option>
                  <option value="qr_tally_scan">qr_tally_scan</option>
                  <option value="rfid_epc_pass">rfid_epc_pass (Observation Only)</option>
                  <option value="coldchain_temp_c">coldchain_temp_c</option>
                </select>
              </div>
              <div>
                <label className="form-label">Target Batch</label>
                <select
                  className="form-select"
                  value={batchId}
                  onChange={(e) => setBatchId(e.target.value)}
                >
                  {batches.map((b) => (
                    <option key={b.batch_id} value={b.batch_id}>
                      {b.batch_id} ({b.item_id})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="form-row-3" style={{ marginTop: '0.5rem' }}>
              <div>
                <label className="form-label">Monotonic Sequence #</label>
                <input
                  type="number"
                  className="form-input"
                  value={customSequence}
                  onChange={(e) => setCustomSequence(Number(e.target.value))}
                />
              </div>
              <div>
                <label className="form-label">Observed Value</label>
                <input
                  type="number"
                  step="0.1"
                  className="form-input"
                  value={valueNum}
                  onChange={(e) => setValueNum(Number(e.target.value))}
                />
              </div>
              <div>
                <label className="form-label">Unit</label>
                <input
                  type="text"
                  className="form-input"
                  value={unitStr}
                  onChange={(e) => setUnitStr(e.target.value)}
                />
              </div>
            </div>

            <div style={{ marginTop: '0.65rem' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handleIngestObservation()}
              >
                <Activity size={14} />
                <span>Transmit Observation to Gateway (`POST /api/v1/observations`)</span>
              </button>
            </div>
          </div>
        </section>

        {/* Right: Section 11 Canonical Observation JSON & Authorized Business Event Promotion */}
        <section className="panel">
          <h3>
            <Barcode size={17} /> Section 11 Canonical Observation Inspector &amp; Promotion Boundary
          </h3>
          <p className="panel-subtext">
            Inspect the raw observation JSON contract (`schema_version: "1.0"`). Notice `occurred_at` (device clock) is stored separately from `gateway_time`, and `status: "PROVISIONAL"` never creates a receipt by itself.
          </p>

          {selectedObs && (
            <>
              <pre className="json-code-block">
                {JSON.stringify(
                  {
                    schema_version: selectedObs.schema_version,
                    event_id: selectedObs.event_id,
                    device_id: selectedObs.device_id,
                    boot_session: selectedObs.boot_session,
                    sequence: selectedObs.sequence,
                    site_id: selectedObs.site_id,
                    batch_id: selectedObs.batch_id,
                    observation_type: selectedObs.observation_type,
                    value: selectedObs.value,
                    unit: selectedObs.unit,
                    occurred_at: selectedObs.occurred_at,
                    gateway_time: selectedObs.gateway_time,
                    calibration_status: selectedObs.calibration_status,
                    origin_evidence: selectedObs.origin_evidence,
                    status: selectedObs.status,
                    anomaly_flags: selectedObs.anomaly_flags,
                  },
                  null,
                  2
                )}
              </pre>

              <div className="promotion-box">
                <div>
                  <strong>Authorized Business Event Promotion (Section 8 Rule 7):</strong>
                  <div className="cell-sub">
                    {selectedObs.status === 'PROVISIONAL'
                      ? 'This verified observation can be linked to an authorized RECEIPT or ISSUE event.'
                      : selectedObs.status === 'PROMOTED_TO_LEDGER_EVENT'
                        ? `Already promoted to ledger event ${selectedObs.promoted_to_event_id}.`
                        : 'Quarantined or duplicate observations are blocked from mutating stock.'}
                  </div>
                </div>
                {selectedObs.status === 'PROVISIONAL' && (
                  <div className="button-row">
                    <select
                      className="form-select"
                      value={promoteType}
                      onChange={(e) => setPromoteType(e.target.value as 'RECEIPT' | 'ISSUE')}
                    >
                      <option value="RECEIPT">RECEIPT (+Stock)</option>
                      <option value="ISSUE">ISSUE (-Stock)</option>
                    </select>
                    <button
                      type="button"
                      className="btn btn-success"
                      onClick={handlePromoteSelected}
                    >
                      <ArrowUpRight size={14} />
                      <span>Promote to Ledger Event</span>
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* Observation Stream Log */}
      <section className="panel">
        <h3>Gateway Observation Stream ({observations.length} events recorded)</h3>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event ID</th>
                <th>Device / Session / Seq</th>
                <th>Batch &amp; Item</th>
                <th>Observation</th>
                <th>Observed vs Gateway Time</th>
                <th>Status &amp; Physical-Truth Flags</th>
                <th>Inspect</th>
              </tr>
            </thead>
            <tbody>
              {observations.map((obs) => {
                const item = items.find((i) => i.item_id === obs.item_id);
                return (
                  <tr
                    key={`${obs.event_id}-${obs.gateway_time}`}
                    className={
                      selectedObs?.event_id === obs.event_id ? 'row-selected' : ''
                    }
                  >
                    <td>
                      <code>{obs.event_id}</code>
                    </td>
                    <td>
                      <strong>{obs.device_id}</strong>
                      <div className="cell-sub">
                        <code>{obs.boot_session}</code> • seq #{obs.sequence}
                      </div>
                    </td>
                    <td>
                      <code>{obs.batch_id}</code>
                      <div className="cell-sub">{item?.name ?? obs.item_id}</div>
                    </td>
                    <td>
                      <strong className="font-mono">
                        {obs.observation_type}: {obs.value} {obs.unit}
                      </strong>
                    </td>
                    <td>
                      <div className="cell-sub">
                        Obs: {obs.occurred_at.slice(11, 19)} UTC
                      </div>
                      <div className="cell-sub">
                        Gwy: {obs.gateway_time.slice(11, 19)} UTC
                      </div>
                    </td>
                    <td>
                      {obs.status === 'PROVISIONAL' && (
                        <span className="badge badge-info">
                          <CheckCircle2 size={13} /> PROVISIONAL (NO STOCK MUTATION)
                        </span>
                      )}
                      {obs.status === 'PROMOTED_TO_LEDGER_EVENT' && (
                        <span className="badge badge-success">
                          <CheckCircle2 size={13} /> LINKED TO {obs.promoted_to_event_id}
                        </span>
                      )}
                      {obs.status === 'DUPLICATE_IGNORED' && (
                        <span className="badge badge-neutral">DUPLICATE IGNORED</span>
                      )}
                      {obs.status === 'QUARANTINED_ANOMALY' && (
                        <span className="badge badge-danger">
                          <ShieldAlert size={13} /> QUARANTINED ANOMALY
                        </span>
                      )}
                      {obs.anomaly_flags.map((f, i) => (
                        <div key={i} className="cell-sub text-danger">
                          • {f}
                        </div>
                      ))}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm btn-secondary"
                        onClick={() => setSelectedObs(obs)}
                      >
                        View JSON
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};
