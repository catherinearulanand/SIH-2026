/**
 * Setu Supply (SIH26251) — Tab 3: 180-Day Forecasting, Constrained GIS Graph Planner & Deterministic Policy Engine
 */

import React, { useEffect, useState } from 'react';
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Compass,
  GitBranch,
  MapPin,
  Send,
  ShieldCheck,
  Sliders,
  TrendingUp,
} from 'lucide-react';
import {
  ApiErrorEnvelope,
  AuthenticatedPersona,
  ForecastModelVersion,
  ForecastRun,
  GISPlan,
  Item,
  Recommendation,
  ScenarioAssumptions,
  Site,
} from '../contracts/api';
import {
  GIS_GRAPH_EDGES,
  GIS_GRAPH_NODES,
  SCENARIO_PRESETS,
} from '../data/syntheticFixtures';
import { ActiveTabId } from '../components/DemoWalkthroughBar';
import { setuApiClient } from '../services/apiClient';
import {
  getSimulatedForecastFailure,
  setSimulatedForecastFailure,
} from '../services/mockContractEngine';

interface ForecastAndGisPlannerViewProps {
  persona: AuthenticatedPersona;
  site: Site;
  items: Item[];
  initialItemId?: string;
  onNavigateTab: (tab: ActiveTabId) => void;
  onRefreshState: () => void;
  onNotify: (msg: string, tone: 'success' | 'error' | 'info') => void;
}

export const ForecastAndGisPlannerView: React.FC<ForecastAndGisPlannerViewProps> = ({
  persona,
  site,
  items,
  initialItemId,
  onNavigateTab,
  onRefreshState,
  onNotify,
}) => {
  const [selectedItemId, setSelectedItemId] = useState<string>(
    initialItemId || 'ITM-RATION-MRE'
  );
  const [preferredModel, setPreferredModel] = useState<ForecastModelVersion>(
    'SEASONAL_NAIVE_7D_V1'
  );
  const [scenario, setScenario] = useState<ScenarioAssumptions>(
    SCENARIO_PRESETS.STORAGE_CAP_40_SPLIT
  );
  const [forecastRun, setForecastRun] = useState<ForecastRun | null>(null);
  const [gisPlan, setGisPlan] = useState<GISPlan | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [simFailure, setSimFailure] = useState<boolean>(getSimulatedForecastFailure());
  const [showSchematicMap, setShowSchematicMap] = useState<boolean>(true);
  const [overrideQtyPacks, setOverrideQtyPacks] = useState<string>('');
  const [overrideReason, setOverrideReason] = useState<string>('');

  useEffect(() => {
    if (initialItemId) {
      setSelectedItemId(initialItemId);
    }
  }, [initialItemId]);

  const activeItem = items.find((i) => i.item_id === selectedItemId) ?? items[0];

  const runCombinedForecastAndPlan = async (
    itemId = selectedItemId,
    scen = scenario,
    model = preferredModel
  ) => {
    try {
      const res = await setuApiClient.createRecommendation(persona, {
        site_id: site.site_id,
        item_id: itemId,
        scenario: scen,
        preferred_model: model,
      });
      setForecastRun(res.forecast_run);
      setGisPlan(res.gis_plan);
      setRecommendation(res.recommendation);
      onRefreshState();
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Failed to compute forecast and GIS plan', 'error');
    }
  };

  useEffect(() => {
    runCombinedForecastAndPlan(selectedItemId, scenario, preferredModel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [site.site_id, selectedItemId]);

  const toggleEdgeClosure = (edgeId: string) => {
    const exists = scenario.closed_edge_ids.includes(edgeId);
    const nextClosed = exists
      ? scenario.closed_edge_ids.filter((id) => id !== edgeId)
      : [...scenario.closed_edge_ids, edgeId];
    const updated: ScenarioAssumptions = {
      ...scenario,
      scenario_id: 'SCEN-CUSTOM-GRAPH',
      label:
        nextClosed.length > 0
          ? `Custom Scenario (${nextClosed.join(', ')} Closed, +${scenario.weather_delay_days}d Delay)`
          : 'Custom Scenario (All Corridors Open)',
      closed_edge_ids: nextClosed,
    };
    setScenario(updated);
    runCombinedForecastAndPlan(selectedItemId, updated, preferredModel);
  };

  const handleToggleFailureMode = (checked: boolean) => {
    setSimulatedForecastFailure(checked);
    setSimFailure(checked);
    runCombinedForecastAndPlan(selectedItemId, scenario, preferredModel);
    onNotify(
      checked
        ? 'Scenario 10 Active: Simulated Forecast Module Failure -> Routed to Pooled/Manual Fallback without blocking workflow.'
        : 'Restored normal forecasting model execution.',
      'info'
    );
  };

  const handleSubmitRequestFromDraft = async () => {
    if (!recommendation) return;
    const customPacks = overrideQtyPacks ? Number(overrideQtyPacks) : null;
    const finalQtyBase =
      customPacks && customPacks > 0
        ? customPacks * activeItem.pack_size_base
        : recommendation.proposed_qty_base;

    if (customPacks && (!overrideReason || overrideReason.trim().length < 4)) {
      onNotify(
        'Overriding recommended quantity requires an explicit override reason.',
        'error'
      );
      return;
    }

    try {
      const res = await setuApiClient.createRequest(persona, {
        client_event_id: `CEV-REQ-${Date.now().toString(36).toUpperCase()}`,
        site_id: site.site_id,
        item_id: activeItem.item_id,
        proposed_qty_base: finalQtyBase,
        source_recommendation_id: recommendation.recommendation_id,
        source_plan_id: recommendation.plan_id,
        override_reason: customPacks ? overrideReason : undefined,
        freshness_warning_acknowledged: true,
      });
      onRefreshState();
      if (res.queued_offline) {
        onNotify(
          `Offline Mode: Queued Provisional Replenishment Request (${res.queued_offline.client_event_id}) in IndexedDB.`,
          'info'
        );
      } else if (res.request) {
        onNotify(
          `Created Replenishment Request ${res.request.request_id} (${finalQtyBase} ${activeItem.base_unit}). Switch to Approval & Fulfilment tab for independent review.`,
          'success'
        );
        onNavigateTab('APPROVAL_RECEIPT');
      }
    } catch (err) {
      const apiErr = err as ApiErrorEnvelope;
      onNotify(apiErr.message || 'Failed to submit replenishment request', 'error');
    }
  };

  return (
    <div className="view-stack">
      {/* Top Scenario & Item Workbench Controls */}
      <section className="panel panel-highlight">
        <div className="panel-header-row">
          <div>
            <div className="eyebrow">
              <Sliders size={14} /> SECTION 5, 7 &amp; 9 — INTEGRATED FORECASTING, CONSTRAINED GIS PLANNER &amp; DETERMINISTIC POLICY
            </div>
            <h2>
              {activeItem.name} <span className="mono-badge">1 {activeItem.pack_name} = {activeItem.pack_size_base} {activeItem.base_unit}</span>
            </h2>
          </div>
          <label className="checkbox-inline">
            <input
              type="checkbox"
              checked={simFailure}
              onChange={(e) => handleToggleFailureMode(e.target.checked)}
            />
            <span>Simulate Forecast Module Failure (Scenario 10 Fallback Test)</span>
          </label>
        </div>

        <div className="form-row-4">
          <div>
            <label className="form-label">1. Select Supply Item</label>
            <select
              className="form-select"
              value={selectedItemId}
              onChange={(e) => setSelectedItemId(e.target.value)}
            >
              {items.map((it) => (
                <option key={it.item_id} value={it.item_id}>
                  {it.item_id} — {it.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="form-label">2. Forecast Model / Challenger</label>
            <select
              className="form-select"
              value={preferredModel}
              onChange={(e) => {
                const m = e.target.value as ForecastModelVersion;
                setPreferredModel(m);
                runCombinedForecastAndPlan(selectedItemId, scenario, m);
              }}
            >
              <option value="SEASONAL_NAIVE_7D_V1">
                Seasonal-Naive (7-Day Cycle Baseline)
              </option>
              <option value="EWMA_ALPHA_03_V1">
                EWMA (α = 0.30 Smoothing Baseline)
              </option>
              <option value="CROSTON_SBA_CHALLENGER_V1">
                Croston-SBA (Intermittent Demand Challenger)
              </option>
              <option value="POOLED_MANUAL_FALLBACK_V1">
                Pooled / Manual Policy Fallback
              </option>
            </select>
          </div>

          <div>
            <label className="form-label">3. GIS &amp; Storage Scenario Preset</label>
            <select
              className="form-select"
              value={scenario.scenario_id}
              onChange={(e) => {
                const found = Object.values(SCENARIO_PRESETS).find(
                  (s) => s.scenario_id === e.target.value
                );
                if (found) {
                  setScenario(found);
                  runCombinedForecastAndPlan(selectedItemId, found, preferredModel);
                }
              }}
            >
              {Object.values(SCENARIO_PRESETS).map((s) => (
                <option key={s.scenario_id} value={s.scenario_id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="form-label">
              4. Storage Headroom ({activeItem.pack_name}s) &amp; Delay (+Days)
            </label>
            <div className="button-row">
              <input
                type="number"
                className="form-input"
                title="Depot receiving storage headroom in packs"
                value={scenario.storage_headroom_packs_limit}
                onChange={(e) => {
                  const next = {
                    ...scenario,
                    storage_headroom_packs_limit: Math.max(10, Number(e.target.value)),
                  };
                  setScenario(next);
                  runCombinedForecastAndPlan(selectedItemId, next, preferredModel);
                }}
              />
              <input
                type="number"
                className="form-input"
                title="Weather/route delay days"
                value={scenario.weather_delay_days}
                onChange={(e) => {
                  const next = {
                    ...scenario,
                    weather_delay_days: Math.max(0, Number(e.target.value)),
                  };
                  setScenario(next);
                  runCombinedForecastAndPlan(selectedItemId, next, preferredModel);
                }}
              />
            </div>
          </div>
        </div>
      </section>

      {/*Warnings Banner if any */}
      {forecastRun && forecastRun.warnings.length > 0 && (
        <div className="alert-banner alert-warning">
          <AlertTriangle size={18} />
          <div>
            <strong>Active Forecast &amp; Evidence Warnings:</strong>
            <ul className="compact-list">
              {forecastRun.warnings.map((w, idx) => (
                <li key={idx}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Two-Column Grid: Constrained GIS Planner (Left) + 180-Day Forecast & Holdout (Right) */}
      <div className="two-col-grid">
        {/* Constrained GIS Logistics Planner */}
        <section className="panel">
          <div className="panel-header-row">
            <div>
              <h3>
                <Compass size={17} /> Constrained GIS Freight Replenishment Planner (`POST /api/v1/planning-runs`)
              </h3>
              <p className="panel-subtext">
                Click any corridor button below to block/reopen an edge (Scenario 11) and compare the Setu Constrained Planner against the Nearest-Feasible-Source Baseline.
              </p>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => setShowSchematicMap((prev) => !prev)}
            >
              {showSchematicMap ? 'Hide Schematic (Tabular Only)' : 'Show Schematic Graph'}
            </button>
          </div>

          {/* Interactive Corridor Closure Toggles */}
          <div className="corridor-toggle-strip">
            {GIS_GRAPH_EDGES.map((edge) => {
              const isClosed = scenario.closed_edge_ids.includes(edge.edge_id);
              const isUsed = gisPlan?.path_refs.includes(edge.edge_id);
              return (
                <button
                  key={edge.edge_id}
                  type="button"
                  className={`corridor-chip ${
                    isClosed
                      ? 'corridor-closed'
                      : isUsed
                        ? 'corridor-active'
                        : 'corridor-open'
                  }`}
                  onClick={() => toggleEdgeClosure(edge.edge_id)}
                >
                  <span>
                    {isClosed ? '⛔ CLOSED' : isUsed ? '🚚 ACTIVE' : '🟢 OPEN'}: {edge.edge_id}
                  </span>
                  <small>
                    {edge.declared_transit_days}d • Cap {edge.max_capacity_packs_per_Window} packs
                  </small>
                </button>
              );
            })}
          </div>

          {/* Fictional SVG Transport Graph */}
          {showSchematicMap && gisPlan && (
            <div className="gis-svg-container">
              <svg
                viewBox="0 0 100 100"
                className="gis-schematic-svg"
                role="img"
                aria-label="Fictional Constrained Logistics Graph"
              >
                {/* Draw Edges */}
                {GIS_GRAPH_EDGES.map((edge) => {
                  const fromNode = GIS_GRAPH_NODES.find(
                    (n) => n.node_id === edge.from_node_id
                  );
                  const toNode = GIS_GRAPH_NODES.find((n) => n.node_id === edge.to_node_id);
                  if (!fromNode || !toNode) return null;
                  const isClosed = scenario.closed_edge_ids.includes(edge.edge_id);
                  const isAllocated = gisPlan.path_refs.includes(edge.edge_id);
                  const midX = (fromNode.fictional_xy.x + toNode.fictional_xy.x) / 2;
                  const midY = (fromNode.fictional_xy.y + toNode.fictional_xy.y) / 2;

                  return (
                    <g key={edge.edge_id}>
                      <line
                        x1={fromNode.fictional_xy.x}
                        y1={fromNode.fictional_xy.y}
                        x2={toNode.fictional_xy.x}
                        y2={toNode.fictional_xy.y}
                        stroke={
                          isClosed ? '#ef4444' : isAllocated ? '#10b981' : '#475569'
                        }
                        strokeWidth={isAllocated ? 1.8 : 1.1}
                        strokeDasharray={isClosed ? '2,2' : undefined}
                      />
                      <text
                        x={midX}
                        y={midY - 1.5}
                        fontSize="2.7"
                        fill={isClosed ? '#fca5a5' : isAllocated ? '#6ee7b7' : '#94a3b8'}
                        textAnchor="middle"
                      >
                        {edge.edge_id} ({isClosed ? 'BLOCKED' : `${edge.declared_transit_days}d`})
                      </text>
                    </g>
                  );
                })}

                {/* Draw Nodes */}
                {GIS_GRAPH_NODES.map((node) => {
                  const isTarget = node.node_id === site.site_id;
                  const isSource = gisPlan.allocations.some(
                    (a) => a.source_node_id === node.node_id
                  );
                  return (
                    <g key={node.node_id}>
                      <circle
                        cx={node.fictional_xy.x}
                        cy={node.fictional_xy.y}
                        r={isTarget ? 4.2 : 3.2}
                        fill={
                          isTarget
                            ? '#3b82f6'
                            : isSource
                              ? '#10b981'
                              : '#1e293b'
                        }
                        stroke="#e2e8f0"
                        strokeWidth="0.7"
                      />
                      <text
                        x={node.fictional_xy.x}
                        y={node.fictional_xy.y + 6.5}
                        fontSize="2.8"
                        fill="#f8fafc"
                        textAnchor="middle"
                        fontWeight="bold"
                      >
                        {node.node_id}
                      </text>
                    </g>
                  );
                })}
              </svg>
              <div className="gis-legend">
                <span>🔵 Target Site ({site.site_id})</span>
                <span>🟢 Allocated Source &amp; Feasible Corridor</span>
                <span>🔴 Blocked Corridor (Click chip to toggle)</span>
                <span>⚠️ Non-Real Fictional Coordinates Only</span>
              </div>
            </div>
          )}

          {/* GIS Plan Results & Baseline Comparison */}
          {gisPlan && (
            <div className="gis-summary-box">
              <div className="gis-status-header">
                <div>
                  <strong>Plan {gisPlan.plan_id}:</strong>{' '}
                  <span
                    className={`badge ${
                      gisPlan.solver_status === 'FEASIBLE_SINGLE_WAVE'
                        ? 'badge-success'
                        : gisPlan.solver_status === 'FEASIBLE_SPLIT_ARRIVAL_REQUIRED'
                          ? 'badge-warning'
                          : 'badge-danger'
                    }`}
                  >
                    {gisPlan.solver_status}
                  </span>
                </div>
                <div className="cell-sub font-mono">
                  Objective Score: {gisPlan.objective_components.total_weighted_objective} (Shortage:{' '}
                  {gisPlan.objective_components.shortage_Check_score} + Transit:{' '}
                  {gisPlan.objective_components.transport_cost_score} + Expiry:{' '}
                  {gisPlan.objective_components.expiry_risk_score})
                </div>
              </div>

              <div className="baseline-compare-banner">
                <strong>Nearest-Feasible-Source Baseline Comparison:</strong>{' '}
                {gisPlan.nearest_source_baseline.comparison_summary}
              </div>

              <div className="table-scroll">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>Source Node</th>
                      <th>Corridor Path</th>
                      <th>Allocated Quantity</th>
                      <th>Transit &amp; ETA</th>
                      <th>Binding Constraint</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gisPlan.allocations.map((alloc, i) => (
                      <tr key={i}>
                        <td>
                          <strong>{alloc.source_node_id}</strong>
                          <div className="cell-sub">{alloc.source_label}</div>
                        </td>
                        <td>
                          <code>{alloc.path_edge_ids.join(' → ')}</code>
                        </td>
                        <td>
                          <strong className="font-mono">
                            {alloc.allocated_packs} {activeItem.pack_name}s ({alloc.allocated_qty_base}{' '}
                            {activeItem.base_unit})
                          </strong>
                        </td>
                        <td>
                          {alloc.transit_days}d → <code>{alloc.expected_arrival_date}</code>
                        </td>
                        <td>
                          {alloc.binding_constraint ? (
                            <span className="text-warn">{alloc.binding_constraint}</span>
                          ) : (
                            <span className="cell-sub">Within corridor capacity</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>

        {/* Right: 180-Day Forecast & Locked Test Evaluation */}
        <section className="panel">
          {forecastRun && (
            <>
              <div className="panel-header-row">
                <div>
                  <h3>
                    <TrendingUp size={17} /> 180-Day Demand Forecast &amp; Locked Test Evaluation (`{forecastRun.run_id}`)
                  </h3>
                  <p className="panel-subtext">
                    Dataset <code>{forecastRun.dataset_fingerprint}</code> (Seed {forecastRun.seed}):{' '}
                    <strong>{forecastRun.evaluation.train_days}d Train</strong> /{' '}
                    <strong>{forecastRun.evaluation.selection_days}d Selection</strong> /{' '}
                    <strong>{forecastRun.evaluation.locked_test_days}d Locked Test</strong>. Range method:{' '}
                    <code>{forecastRun.range_method}</code>.
                  </p>
                </div>
              </div>

              {/* SVG Horizon Forecast & Depletion Chart */}
              <div className="chart-box">
                <div className="chart-caption">
                  <span>
                    {forecastRun.horizon}-Day Horizon Demand Outlook &amp; Scenario Envelope ({activeItem.base_unit}/day)
                  </span>
                  <span>
                    Cumulative Expected:{' '}
                    <strong>
                      {forecastRun.horizon_cumulative_expected_base} {activeItem.base_unit} (
                      {(
                        forecastRun.horizon_cumulative_expected_base / activeItem.pack_size_base
                      ).toFixed(1)}{' '}
                      {activeItem.pack_name}s)
                    </strong>{' '}
                    [Envelope: {forecastRun.horizon_cumulative_lower_base}–
                    {forecastRun.horizon_cumulative_upper_base}]
                  </span>
                </div>

                <svg
                  viewBox="0 0 600 175"
                  className="forecast-svg"
                  role="img"
                  aria-label="Horizon Demand Forecast and Usable Stock Trajectory"
                >
                  {(() => {
                    const pts = forecastRun.daily_points;
                    if (pts.length === 0) return null;
                    const maxVal = Math.max(
                      ...pts.map((p) =>
                        Math.max(p.upper_base, p.projected_usable_stock_base / 4, 50)
                      )
                    );
                    const xStep = 520 / Math.max(1, pts.length - 1);
                    const toX = (i: number) => 45 + i * xStep;
                    const toY = (v: number) => 145 - (v / maxVal) * 120;

                    const areaPoints = [
                      ...pts.map((p, i) => `${toX(i)},${toY(p.upper_base)}`),
                      ...[...pts]
                        .reverse()
                        .map((p, i) => `${toX(pts.length - 1 - i)},${toY(p.lower_base)}`),
                    ].join(' ');

                    const snPoly = pts
                      .map((p, i) => `${toX(i)},${toY(p.seasonal_naive_base)}`)
                      .join(' ');
                    const ewmaPoly = pts
                      .map((p, i) => `${toX(i)},${toY(p.ewma_base)}`)
                      .join(' ');
                    const selPoly = pts
                      .map((p, i) => `${toX(i)},${toY(p.selected_base)}`)
                      .join(' ');

                    return (
                      <>
                        {/* Grid lines */}
                        <line x1="45" y1="25" x2="575" y2="25" stroke="#334155" strokeWidth="0.6" />
                        <line x1="45" y1="85" x2="575" y2="85" stroke="#334155" strokeWidth="0.6" />
                        <line x1="45" y1="145" x2="575" y2="145" stroke="#475569" strokeWidth="1" />

                        {/* Scenario Envelope Band */}
                        <polygon points={areaPoints} fill="rgba(59, 130, 246, 0.18)" />

                        {/* EWMA Comparison Line */}
                        <polyline
                          fill="none"
                          stroke="#94a3b8"
                          strokeWidth="1.5"
                          strokeDasharray="3,3"
                          points={ewmaPoly}
                        />
                        {/* Seasonal Naive Line */}
                        <polyline
                          fill="none"
                          stroke="#38bdf8"
                          strokeWidth="1.5"
                          points={snPoly}
                        />
                        {/* Selected Model Point Forecast */}
                        <polyline
                          fill="none"
                          stroke="#10b981"
                          strokeWidth="2.4"
                          points={selPoly}
                        />

                        {pts.map((p, i) => (
                          <g key={p.date}>
                            <circle
                              cx={toX(i)}
                              cy={toY(p.selected_base)}
                              r="2.8"
                              fill="#10b981"
                            />
                            {i % 2 === 0 && (
                              <text
                                x={toX(i)}
                                y="162"
                                fontSize="9"
                                fill="#94a3b8"
                                textAnchor="middle"
                              >
                                {p.date.slice(5)}
                              </text>
                            )}
                          </g>
                        ))}
                      </>
                    );
                  })()}
                </svg>
                <div className="gis-legend">
                  <span>🟢 Selected Model ({forecastRun.model_version})</span>
                  <span>🔵 Seasonal-Naive 7d Baseline</span>
                  <span>⚪ EWMA (α=0.3) Baseline</span>
                  <span>🟦 Scenario Envelope (Uncalibrated Band)</span>
                </div>
              </div>

              {/* Chronological Holdout Metrics Table */}
              <h4>{forecastRun.evaluation.label}</h4>
              <div className="table-scroll">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>Model / Baseline</th>
                      <th>MAE ({activeItem.base_unit})</th>
                      <th>WAPE (%)</th>
                      <th>Bias ({activeItem.base_unit})</th>
                      <th>Role in Architecture</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>
                        <strong>Seasonal-Naive (7-Day)</strong>
                      </td>
                      <td className="font-mono">{forecastRun.evaluation.seasonal_naive_mae}</td>
                      <td className="font-mono">
                        {forecastRun.evaluation.seasonal_naive_wape !== null
                          ? `${forecastRun.evaluation.seasonal_naive_wape}%`
                          : 'N/A (Zero Denom)'}
                      </td>
                      <td className="font-mono">{forecastRun.evaluation.seasonal_naive_bias}</td>
                      <td>Primary weekly-cycle baseline</td>
                    </tr>
                    <tr>
                      <td>
                        <strong>EWMA (α = 0.30)</strong>
                      </td>
                      <td className="font-mono">{forecastRun.evaluation.ewma_mae}</td>
                      <td className="font-mono">
                        {forecastRun.evaluation.ewma_wape !== null
                          ? `${forecastRun.evaluation.ewma_wape}%`
                          : 'N/A'}
                      </td>
                      <td className="font-mono">{forecastRun.evaluation.ewma_bias}</td>
                      <td>Smooth level-shift comparator</td>
                    </tr>
                    <tr>
                      <td>
                        <strong>Croston-SBA Challenger</strong>
                      </td>
                      <td className="font-mono">{forecastRun.evaluation.croston_sba_mae}</td>
                      <td className="font-mono">
                        {forecastRun.evaluation.croston_sba_wape !== null
                          ? `${forecastRun.evaluation.croston_sba_wape}%`
                          : 'N/A'}
                      </td>
                      <td className="font-mono">{forecastRun.evaluation.croston_sba_bias}</td>
                      <td>Intermittent-demand challenger (e.g. Thermal Clothing)</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>

      {/* Bottom Full-Width Panel: Section 5 Replenishment Formula, Deterministic Policy Engine & Evidence-to-Decision Packet */}
      {recommendation && gisPlan && (
        <section className="panel panel-highlight">
          <div className="panel-header-row">
            <div>
              <div className="eyebrow">
                <ShieldCheck size={14} /> SECTION 5, 9 &amp; 17 — REPLENISHMENT TRACE, DETERMINISTIC POLICY ENGINE &amp; DECISION PACKET
              </div>
              <h3>
                Draft Recommendation <code>{recommendation.recommendation_id}</code> — Read-Only Advisory Proposal
              </h3>
            </div>
            <span
              className={`badge ${
                recommendation.policy_evaluation.decision === 'ALLOW'
                  ? 'badge-success'
                  : recommendation.policy_evaluation.decision === 'REQUIRES_REVIEW'
                    ? 'badge-warning'
                    : 'badge-danger'
              }`}
            >
              {recommendation.policy_evaluation.decision === 'ALLOW' ? (
                <CheckCircle2 size={14} />
              ) : (
                <AlertOctagon size={14} />
              )}
              <span>
                POLICY ENGINE: {recommendation.policy_evaluation.decision} (
                {recommendation.policy_evaluation.policy_version})
              </span>
            </span>
          </div>

          {/* Section 5 Illustrative Replenishment Calculation Formula Strip */}
          <div className="formula-strip">
            <div className="formula-box">
              <span className="formula-label">Expected Horizon Demand</span>
              <strong className="formula-val">
                {(
                  recommendation.expected_horizon_demand_base / activeItem.pack_size_base
                ).toFixed(0)}{' '}
                {activeItem.pack_name}s
              </strong>
              <small>
                {recommendation.expected_horizon_demand_base} {activeItem.base_unit}
              </small>
            </div>
            <div className="formula-op">+</div>
            <div className="formula-box">
              <span className="formula-label">
                Declared Buffer ({recommendation.assumptions.buffer_policy_pct}%)
              </span>
              <strong className="formula-val">
                {(recommendation.declared_buffer_base / activeItem.pack_size_base).toFixed(0)}{' '}
                {activeItem.pack_name}s
              </strong>
              <small>
                {recommendation.declared_buffer_base} {activeItem.base_unit}
              </small>
            </div>
            <div className="formula-op">−</div>
            <div className="formula-box">
              <span className="formula-label">Allocatable Stock</span>
              <strong className="formula-val">
                {(recommendation.current_allocatable_base / activeItem.pack_size_base).toFixed(
                  0
                )}{' '}
                {activeItem.pack_name}s
              </strong>
              <small>
                {recommendation.current_allocatable_base} {activeItem.base_unit} (Usable − Reserved)
              </small>
            </div>
            <div className="formula-op">−</div>
            <div className="formula-box">
              <span className="formula-label">Confirmed Inbound</span>
              <strong className="formula-val">
                {(
                  recommendation.confirmed_inbound_due_base / activeItem.pack_size_base
                ).toFixed(0)}{' '}
                {activeItem.pack_name}s
              </strong>
              <small>
                {recommendation.confirmed_inbound_due_base} {activeItem.base_unit}
              </small>
            </div>
            <div className="formula-op">=</div>
            <div className="formula-box formula-box-result">
              <span className="formula-label">Draft Requirement</span>
              <strong className="formula-val">
                {recommendation.proposed_packs} {activeItem.pack_name}s
              </strong>
              <small>
                {recommendation.proposed_qty_base} {activeItem.base_unit}
              </small>
            </div>
            <div className="formula-op">→</div>
            <div className="formula-box formula-box-wave">
              <span className="formula-label">
                Storage Cap ({gisPlan.storage_headroom_packs} {activeItem.pack_name}s)
              </span>
              <strong className="formula-val">
                Wave 1: {recommendation.feasible_packs} | Wave 2:{' '}
                {gisPlan.split_second_wave_packs} | Unmet: {gisPlan.unmet_packs}
              </strong>
              <small>Split-Arrival / Feasibility Check</small>
            </div>
          </div>

          <div className="two-col-grid" style={{ marginTop: '0.85rem' }}>
            {/* Deterministic Policy Checks */}
            <div>
              <h4>
                <GitBranch size={15} /> Server-Side Deterministic Policy Checks (Section 9)
              </h4>
              <div className="table-scroll">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>Rule ID</th>
                      <th>Status</th>
                      <th>Evaluation Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recommendation.policy_evaluation.checks.map((chk) => (
                      <tr key={chk.rule_id}>
                        <td>
                          <code>{chk.rule_id}</code>
                          <div className="cell-sub">{chk.rule_label}</div>
                        </td>
                        <td>
                          <span
                            className={`badge ${
                              chk.status === 'PASS'
                                ? 'badge-success'
                                : chk.status === 'REVIEW_FLAG'
                                  ? 'badge-warning'
                                  : 'badge-danger'
                            }`}
                          >
                            {chk.status}
                          </span>
                        </td>
                        <td>{chk.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Alternatives Considered & Submit Request Form */}
            <div>
              <h4>
                <MapPin size={15} /> Evidence-to-Decision Alternatives &amp; Request Submission
              </h4>
              <div className="table-scroll">
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th>Option</th>
                      <th>Proposed</th>
                      <th>Shortage Days</th>
                      <th>Tradeoff Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recommendation.evidence_record.alternatives_considered.map((alt, i) => (
                      <tr key={i}>
                        <td>
                          <strong>{alt.option_label}</strong>
                        </td>
                        <td className="font-mono">
                          {alt.proposed_packs} {activeItem.pack_name}s ({alt.proposed_qty_base}{' '}
                          {activeItem.base_unit})
                        </td>
                        <td className="font-mono">{alt.expected_shortage_days}d</td>
                        <td className="cell-sub">{alt.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="submit-request-card">
                <div className="form-row-3">
                  <div>
                    <label className="form-label">
                      Optional Override ({activeItem.pack_name}s)
                    </label>
                    <input
                      type="number"
                      className="form-input"
                      placeholder={`Default: ${recommendation.proposed_packs}`}
                      value={overrideQtyPacks}
                      onChange={(e) => setOverrideQtyPacks(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="form-label">Override / Split-Arrival Note</label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="Reason if overriding recommended packs..."
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{ width: '100%' }}
                      onClick={handleSubmitRequestFromDraft}
                    >
                      <Send size={14} />
                      <span>Submit Request for Independent Approval</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};
