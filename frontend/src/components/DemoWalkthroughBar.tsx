/**
 * Setu Supply (SIH26251) — Section 20 Three-Minute Demonstration Video Script & Scenario Runner
 */

import React, { useState } from 'react';
import { ChevronRight, Film, PlayCircle, Sparkles } from 'lucide-react';

export type ActiveTabId =
  | 'WORKBENCH'
  | 'IOT_GATEWAY'
  | 'FORECAST_GIS'
  | 'APPROVAL_RECEIPT'
  | 'OFFLINE_AUDIT';

export interface VideoScriptStep {
  step_index: number;
  time_window: string;
  title: string;
  target_tab: ActiveTabId;
  narration: string;
  action_hint: string;
}

export const THREE_MINUTE_VIDEO_STEPS: VideoScriptStep[] = [
  {
    step_index: 1,
    time_window: '0:00–0:15',
    title: 'Fictional-Site Notice & Snapshot Authority',
    target_tab: 'WORKBENCH',
    narration:
      '“Setu Supply demonstrates predictive general-supply assurance using synthetic data and fictional locations.”',
    action_hint: 'Show Depot Digital Representation header, frozen snapshot v14, and owned exception cards.',
  },
  {
    step_index: 2,
    time_window: '0:15–0:35',
    title: 'CSV Import Quarantine & Simulated Scanner Stream',
    target_tab: 'IOT_GATEWAY',
    narration:
      '“We preserve source evidence and reject uncertain mappings. This capture stream is simulated, as labelled.”',
    action_hint:
      'Inspect evt-demo-00042 barcode scan, test duplicate sequence replay & cold-chain excursion, or run CSV import validation.',
  },
  {
    step_index: 3,
    time_window: '0:35–0:55',
    title: 'Usable vs Gross Stock, Expiry & Freshness Trio',
    target_tab: 'WORKBENCH',
    narration:
      '“Physical stock is not the same as usable stock. Here an expiring batch and an old observation change what the planner can rely on.”',
    action_hint:
      'Point to MRE usable (60 Crates) vs expired (10 Crates) vs reserved (10 Crates) = 50 Crates allocatable, plus 99h stale count flag.',
  },
  {
    step_index: 4,
    time_window: '0:55–1:20',
    title: '180-Day Forecast (120/30/30) & Baseline Holdout',
    target_tab: 'FORECAST_GIS',
    narration:
      '“The demand outlook is compared with a simple baseline. Its range is labelled by method; low evidence stays visible.”',
    action_hint:
      'Show Seasonal-Naive vs EWMA vs Croston-SBA metrics on 30-day locked test and test sparse-history item ITM-MED-ANTISEP.',
  },
  {
    step_index: 5,
    time_window: '1:20–1:45',
    title: 'Constrained GIS Graph: Close Corridor N1 & Recompute',
    target_tab: 'FORECAST_GIS',
    narration:
      '“A declared delay changes feasible arrival. The planner checks source and transport constraints and reports unmet demand if no option works.”',
    action_hint:
      'Toggle Corridor EDG-N1-MAIN closed or switch to Scenario 2 (40-Pack Storage Cap -> Split Arrival) / Scenario 4 (Unmet Demand).',
  },
  {
    step_index: 6,
    time_window: '1:45–2:05',
    title: 'Draft Recommendation Packet & Independent Approval Check',
    target_tab: 'APPROVAL_RECEIPT',
    narration:
      '“The recommendation is a draft. Its creator cannot approve it. An independent reviewer sees assumptions and the server rechecks current state.”',
    action_hint:
      'Try approving REQ-2026-0101 as Storekeeper (blocked 403), then switch persona to Maj. A. Verma (Approver) and approve.',
  },
  {
    step_index: 7,
    time_window: '2:05–2:35',
    title: 'Offline Provisional Receipt, Reconnect & Idempotent Retry',
    target_tab: 'APPROVAL_RECEIPT',
    narration:
      '“Offline evidence is provisional. On reconnect it is validated. Replaying this receipt does not increase stock twice, and the missing balance remains unresolved.”',
    action_hint:
      'Record partial receipt offline or click "Test Duplicate Receipt Key Retry (Scenario 1)" on SHP-2026-901.',
  },
  {
    step_index: 8,
    time_window: '2:35–2:50',
    title: 'Audit Lineage, Evaluation & Subordinate Extensions',
    target_tab: 'OFFLINE_AUDIT',
    narration:
      '“We retain the input snapshot, policy, decision and actual receipt. These results are measured synthetic results, as labelled.”',
    action_hint:
      'Inspect append-only audit chain, Source Authority Registry, Optional Local Assistant (test prompt injection), and Custody Digests.',
  },
];

interface DemoWalkthroughBarProps {
  activeTab: ActiveTabId;
  onSelectTab: (tab: ActiveTabId) => void;
  onTriggerDemoAction?: (stepIndex: number) => void;
}

export const DemoWalkthroughBar: React.FC<DemoWalkthroughBarProps> = ({
  onSelectTab,
  onTriggerDemoAction,
}) => {
  const [activeStepIdx, setActiveStepIdx] = useState<number>(0);
  const [expanded, setExpanded] = useState<boolean>(true);

  const currentStep = THREE_MINUTE_VIDEO_STEPS[activeStepIdx];

  return (
    <section className="demo-walkthrough-bar" aria-label="3-Minute SIH Video Walkthrough">
      <div className="demo-bar-header">
        <div className="demo-bar-title">
          <Film size={15} />
          <strong>Section 20 — 3-Minute Demo Video Script &amp; Live Rehearsal Cue</strong>
          <span className="demo-synthetic-pill">
            <Sparkles size={12} /> Synthetic Data &amp; Fictional Sites Only
          </span>
        </div>
        <button
          type="button"
          className="btn-link"
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? 'Minimize Script Bar' : 'Expand 3-Min Video Script'}
        </button>
      </div>

      {expanded && (
        <>
          <div className="demo-steps-track">
            {THREE_MINUTE_VIDEO_STEPS.map((st, idx) => {
              const isCurrent = idx === activeStepIdx;
              return (
                <button
                  key={st.step_index}
                  type="button"
                  className={`demo-step-pill ${isCurrent ? 'demo-step-pill-active' : ''}`}
                  onClick={() => {
                    setActiveStepIdx(idx);
                    onSelectTab(st.target_tab);
                    if (onTriggerDemoAction) onTriggerDemoAction(st.step_index);
                  }}
                >
                  <span className="demo-step-time">{st.time_window}</span>
                  <span className="demo-step-name">{st.title}</span>
                </button>
              );
            })}
          </div>

          <div className="demo-active-cue">
            <div className="demo-cue-main">
              <span className="demo-cue-badge">
                <PlayCircle size={14} /> {currentStep.time_window}
              </span>
              <p className="demo-cue-narration">{currentStep.narration}</p>
            </div>
            <div className="demo-cue-right">
              <span className="demo-cue-hint">{currentStep.action_hint}</span>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  const next = (activeStepIdx + 1) % THREE_MINUTE_VIDEO_STEPS.length;
                  setActiveStepIdx(next);
                  onSelectTab(THREE_MINUTE_VIDEO_STEPS[next].target_tab);
                  if (onTriggerDemoAction) {
                    onTriggerDemoAction(THREE_MINUTE_VIDEO_STEPS[next].step_index);
                  }
                }}
              >
                <span>Next Scene</span>
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
};
