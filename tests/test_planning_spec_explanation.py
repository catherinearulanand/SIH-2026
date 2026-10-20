"""Spec: scenario changes must change the plan, and the explanation must say why using only facts."""

from planning_helpers import busiest_edge, custom, plan_for, scenarios, world
from setu.planning.graph import load_base_graph


def _base():
    return plan_for(scenarios()["base"])


def _shape(plan):
    return sorted((a.item, a.source, a.dest, a.qty, tuple(plan.path_refs[a.path_ref])) for a in plan.allocations)


def test_closing_a_used_edge_changes_the_plan_and_the_explanation_ties_it_to_a_base_path():
    base = _base()
    eid = busiest_edge(base)
    plan = plan_for(custom("close-used", closed_edges=[eid]))

    assert all(eid not in plan.path_refs[a.path_ref] for a in plan.allocations)
    assert _shape(plan) != _shape(base), "closing a used edge left the plan unchanged"

    affected = [r for r, edges in base.path_refs.items() if eid in edges]
    lines = [l for l in plan.explanation if eid in l]
    assert lines, f"no explanation line names closed edge {eid}: {plan.explanation}"
    assert any(r in l for l in lines for r in affected), (
        f"explanation does not tie {eid} to an affected base path {affected}: {lines}"
    )


def test_scenario_lines_carry_label_and_hypothetical_flag():
    sc = custom("close-used", closed_edges=[busiest_edge(_base())])
    plan = plan_for(sc)
    assert plan.scenario_label == sc.label
    lines = [l for l in plan.explanation if sc.label in l]
    assert lines and all("Hypothetical" in l for l in lines)


def test_delay_that_breaks_the_window_is_cited_and_respected():
    snap, _ = world()
    eid = busiest_edge(_base())
    plan = plan_for(custom("delay-used", delay_h={eid: 500.0}))
    window = {s.site_id: s.delivery_window_h for s in snap.sites}
    assert all(a.arrival_h <= window[a.dest] for a in plan.allocations)
    assert all(eid not in plan.path_refs[a.path_ref] for a in plan.allocations)
    assert any(eid in l and "window" in l.lower() for l in plan.explanation), plan.explanation


def test_closing_an_unused_edge_changes_nothing_and_claims_no_reroute():
    base = _base()
    used = {e for r in base.path_refs.values() for e in r}
    every = {d["edge_id"] for *_, d in load_base_graph().edges(data=True)}
    unused = sorted(every - used)
    assert unused, "base plan uses every edge; fixture too small for this check"
    plan = plan_for(custom("close-unused", closed_edges=[unused[0]]))
    claims = [l for l in plan.explanation if unused[0] in l and ("reroute" in l.lower() or "previous path" in l.lower())]
    assert not claims, claims
    assert _shape(plan) == _shape(base)
