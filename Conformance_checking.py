# =================================================
# Hierarchical Alignment-Based Conformance Checking
# =================================================
from datetime import datetime, timedelta
import sys

from graphviz import Digraph
from matplotlib.pylab import dot
import pm4py
from sklearn.base import defaultdict

from Visualizer import visualise_conformance_result

sys.path.append(r"./cpn-py")
from typing import Dict, List, Set, Any, cast
from dataclasses import dataclass
import pandas as pd

from pm4py.algo.conformance.alignments.petri_net import algorithm as alignments
from pm4py.objects.log.obj import EventLog, Trace, Event
from pm4py.objects.petri_net.obj import PetriNet, Marking
from pm4py.visualization.petri_net import visualizer as pn_visualizer
from pm4py.objects.log.util import dataframe_utils
from pm4py.objects.conversion.log import converter as log_converter
from pm4py.algo.discovery.inductive import algorithm as inductive_miner
from cpnpy.cpn.cpn_imp import CPN, Place
from cpnpy.hcpn.hcpn_imp import HCPN

# Assuming EventLog2EventLogTree and build_hcpn_from_event_logs
# are in the same folder or sys.path
from EventLog2EventLogTree import (
    DeviceComponentNode,
    EventLog2EventLogTree,
    InteractionNode,
)
from EventLog2HCPN import build_hcpn_from_event_logs

# -------------------------------------------------
DEVIATION = ">>"
# -------------------------------------------------


@dataclass
class Deviation:
    move_type: str  # "log", "model", "sync", "skip"
    activity: str
    module: str
    alignment_result: str = ""


def transform_cpn_to_net(cpn: CPN, module_name: str):
    """
    Convert a flat cpn-py CPN into a pm4py Petri net + initial/final markings
    """
    net = PetriNet(module_name)
    im, fm = Marking(), Marking()

    # Create places
    place_map = {}
    for p in cpn.places:
        pm = PetriNet.Place(p.name)
        net.places.add(pm)
        place_map[p] = pm
    # Create transitions
    trans_map = {}
    for t in cpn.transitions:
        tm = PetriNet.Transition(
            t.name, None if t.name.lower().endswith("@silent") else t.name
        )
        net.transitions.add(tm)
        trans_map[t] = tm

    # Create arcs
    for arc in cpn.arcs:
        if arc.source in place_map:
            source = place_map[arc.source]
        else:
            source = trans_map[arc.source]

        if arc.target in place_map:
            target = place_map[arc.target]
        else:
            target = trans_map[arc.target]

        a = PetriNet.Arc(source, target)
        source.out_arcs.add(a)
        target.in_arcs.add(a)
        net.arcs.add(a)

    im = Marking()
    source_places = [p for p in net.places if len(p.in_arcs) == 0]
    sink_places = [p for p in net.places if len(p.out_arcs) == 0]

    im = Marking()
    im[source_places[0]] = 1

    fm = Marking()
    fm[sink_places[0]] = 1

    return net, im, fm


def build_full_device_df(device_node: DeviceComponentNode) -> pd.DataFrame:
    """
    Converts a DeviceComponentNode into a pandas DataFrame suitable for PM4Py,
    where each row represents an event (sensor or actuator) and events are ordered
    by timestamp.
    """
    # Merge all events
    merged_events = []

    for v in device_node.V_d_E:
        e = v.e_s
        merged_events.append(
            {
                "type": "sensor",
                "case:concept:name": e.c_s,
                "concept:name": e.a_s,
                "time:timestamp": e.t,
                "val": e.val,
                "d": e.d,
                "sid": e.sid,
            }
        )

    for v in device_node.V_d_A:
        e = v.e_a
        merged_events.append(
            {
                "type": "actuator",
                "case:concept:name": e.c_a,
                "concept:name": e.a_cmd,
                "time:timestamp": e.t,
                "s_pre": e.s_pre,
                "s_post": e.s_post,
                "d": e.d,
                "id": e.id,
            }
        )
    for v in device_node.V_d_I:
        e = v.e_i
        merged_events.append(
            {
                "type": "interaction",
                "case:concept:name": e.c_i,
                "concept:name": e.a_i,
                "time:timestamp": e.t,
                "d_s": e.d_s,
                "d_t": e.d_t,
                "d_p": e.d_p,
            }
        )

    return merged_events


def event_matches_interaction(e, interaction_node):
    return (
        getattr(e, "a_i", None) == interaction_node.a_i
        and getattr(e, "t", None) == interaction_node.t
        and (
            getattr(e, "d_s", None) is None
            or getattr(e, "d_s", None) == interaction_node.v_d_s.d
        )
        and (
            getattr(e, "d_t", None) is None
            or getattr(e, "d_t", None) == interaction_node.v_d_t.d
        )
        and (
            getattr(e, "d_p", None) is None
            or getattr(e, "d_p", None) == interaction_node.d_p
        )
    )


def findEvent(interaction_node: InteractionNode, direction=-1):
    found_event = None
    event_dict = (
        interaction_node.v_d_s.event_dict
        if direction == -1
        else interaction_node.v_d_t.event_dict
    )
    for event_list in event_dict.values():
        for idx, event in enumerate(event_list):
            if getattr(event, "a_i", None) == interaction_node.a_i:
                if idx + direction >= 0 and idx + direction < len(event_list):
                    found_event = event_list[idx + direction]
                else:
                    found_event = None
                break
        if found_event is not None:
            break
    # found_event = events[idx + direction]
    if getattr(found_event, "c_i", None) != None:
        return {
            "case:concept:name": interaction_node.c_i,#getattr(found_event, "c_i"),
            "concept:name": getattr(found_event, "a_i"),
            "time:timestamp": getattr(found_event, "t"),
            "d_s": getattr(found_event, "d_s"),
            "d_t": getattr(found_event, "d_t"),
            "d_p": getattr(found_event, "d_p"),
        }
    elif getattr(found_event, "c_a", None) != None:
        return {
            "case:concept:name": interaction_node.c_i, #getattr(found_event, "c_a"),
            "concept:name": getattr(found_event, "a_cmd"),
            "time:timestamp": getattr(found_event, "t"),
            "s_pre": getattr(found_event, "s_pre"),
            "s_post": getattr(found_event, "s_post"),
            "d": getattr(found_event, "d"),
        }
    elif getattr(found_event, "c_s", None) != None:
        return {
            "case:concept:name": interaction_node.c_i, #getattr(found_event, "c_s"),
            "concept:name": getattr(found_event, "a_s"),
            "time:timestamp": getattr(found_event, "t"),
            "val": getattr(found_event, "val"),
            "d": getattr(found_event, "d"),
            "sid": getattr(found_event, "sid"),
        }
    return None


def build_interaction_df(interaction_node: InteractionNode) -> pd.DataFrame:
    interaction_event = []
    # pre_events = interaction_node.v_d_s.event_dict.get(interaction_node.c_i, [])
    pre_event = findEvent(interaction_node, -1)
    # post_events = interaction_node.v_d_t.event_dict.get(interaction_node.c_i, [])
    post_event = findEvent(interaction_node, 1)
    
    interaction_time = interaction_node.t
    epsilon = timedelta(microseconds=1)  # minimal safe shift
    
    if pre_event is not None:
        pre_event["time:timestamp"] = interaction_time - epsilon
        interaction_event.append(pre_event)

    interaction_event.append(
        {
            "case:concept:name": interaction_node.c_i,
            "concept:name": interaction_node.a_i,
            "time:timestamp": interaction_time,
            "m_i": None,
            "d_s": interaction_node.v_d_s.d,
            "d_t": interaction_node.v_d_t.d,
            "d_p": interaction_node.d_p,
        }
    )

    if post_event is not None:
        post_event["time:timestamp"] = interaction_time + epsilon
        interaction_event.append(post_event)
    return interaction_event


def align_petri_net(event_list, net, im, fm, skip_cost, module_name):
    df = pd.DataFrame(event_list)
    df_log = df.sort_values(by="time:timestamp").reset_index(drop=True)
    df = dataframe_utils.convert_timestamp_columns_in_df(df_log)
    event_log = log_converter.apply(df, variant=log_converter.Variants.TO_EVENT_LOG)

    # ret_tuple_as_trans_desc: return the alignment steps as tuple of (log move, model move) with activity names
    aligned_log = alignments.apply_log(event_log, net, im, fm)

    alignment, cost, deviations = [], 0, []

    for trace_alignment in aligned_log:
        alignment_result = ",".join(map(str, trace_alignment["alignment"]))
        for log_move, model_move in trace_alignment["alignment"]:
            if log_move == ">>" and model_move != None:
                cost += skip_cost
                deviations.append(Deviation("model", model_move, module_name, alignment_result))
            elif model_move == ">>" and log_move != None:
                cost += skip_cost
                deviations.append(Deviation("log", log_move, module_name, alignment_result))
            elif log_move != None and model_move != None:
                alignment.append((log_move, model_move))

    return alignment, cost, deviations


# -------------------------------------------------
def align_device_node(hcpn: HCPN, module_name: str, device_node, skip_cost: int):
    cpn = hcpn.modules[module_name]
    net, im, fm = transform_cpn_to_net(cpn, module_name)

    event_list = build_full_device_df(device_node)

    alignment, cost, deviations = align_petri_net(
        event_list, net, im, fm, skip_cost, module_name
    )

    return alignment, cost, deviations


def build_place_to_incoming_transitions(sub_cpn):
    """
    Build an index: Place -> list of transitions that have arcs to this place.
    This avoids scanning all arcs repeatedly.
    """
    place_to_prev = defaultdict(list)
    for arc in sub_cpn.arcs:
        if isinstance(arc.target, Place):
            place_to_prev[arc.target].append(arc.source)
    return place_to_prev


def find_previous_non_silent_transitions(sub_cpn, start_transition):
    """
    Iterative backward traversal through the CPN, skipping silent transitions.
    Handles cycles safely.

    Args:
        sub_cpn: The subnet object containing arcs and places.
        start_transition: The transition from which to start backward traversal.

    Returns:
        A set of unique non-silent predecessor transitions.
    """
    # Build index once
    place_to_prev = build_place_to_incoming_transitions(sub_cpn)

    result = set()
    visited = set()  # stores (transition, place) to prevent cycles
    stack = [start_transition]

    while stack:
        transition = stack.pop()

        in_arcs = sub_cpn.get_input_arcs(transition) or []

        for in_arc in in_arcs:
            place = in_arc.source
            state = (transition, place)
            if state in visited:
                continue
            visited.add(state)

            for prev_transition in place_to_prev.get(place, []):
                name = getattr(prev_transition, "name", "").lower()
                if name.startswith("silent"):
                    # Continue searching backward through silent transitions
                    stack.append(prev_transition)
                else:
                    result.add(prev_transition)

    return result


def build_place_to_outgoing_transitions(sub_cpn):
    """
    Build an index: Place -> list of transitions that have arcs from this place.
    This avoids scanning all arcs repeatedly.
    """
    place_to_next = defaultdict(list)
    for arc in sub_cpn.arcs:
        if isinstance(arc.source, Place):
            place_to_next[arc.source].append(arc.target)
    return place_to_next


def find_next_non_silent_transitions(sub_cpn, start_transition):
    """
    Iterative forward traversal through the CPN, skipping silent transitions.
    Handles cycles safely.

    Args:
        sub_cpn: The subnet object containing arcs and places.
        start_transition: The transition from which to start forward traversal.

    Returns:
        A set of unique non-silent successor transitions.
    """
    # Build index once
    place_to_next = build_place_to_outgoing_transitions(sub_cpn)

    result = set()
    visited = set()  # stores (transition, place) to prevent cycles
    stack = [start_transition]

    while stack:
        transition = stack.pop()

        # Get all output places from this transition
        out_arcs = [
            a
            for a in sub_cpn.arcs
            if a.source == transition and isinstance(a.target, Place)
        ]

        for place in [a.target for a in out_arcs]:
            state = (transition, place)
            if state in visited:
                continue
            visited.add(state)

            # Get all transitions connected from this place
            for next_transition in place_to_next.get(place, []):
                if not hasattr(next_transition, "name"):
                    continue
                name = next_transition.name.lower()
                if name.startswith("silent"):
                    # Continue forward through silent transitions
                    stack.append(next_transition)
                else:
                    result.add(next_transition)

    return result


def find_pre_transition(hcpn: HCPN, pre_cpn: str, interaction_node: InteractionNode):
    sub_cpn = hcpn.modules.get(pre_cpn)
    if not sub_cpn:
        return None
    transition_in_pre = sub_cpn.get_transition_by_name(interaction_node.a_i)
    if not transition_in_pre:
        return None
    pre_transitions = find_previous_non_silent_transitions(sub_cpn, transition_in_pre)
    pre_transitions = [t for t in pre_transitions if t.name != transition_in_pre.name]
    return pre_transitions.pop() if pre_transitions else None


def find_post_transition(hcpn: HCPN, post_cpn: str, interaction_node: InteractionNode):
    """
    Find a post-transition (successor) in the subnet, skipping silent transitions.

    Args:
        hcpn: The hierarchical CPN object containing modules.
        post_cpn: The name of the subnet/module to search.
        interaction_node: The node containing the transition name (a_i).

    Returns:
        A single non-silent successor transition, or None if not found.
    """
    # Get the subnet
    sub_cpn = hcpn.modules.get(post_cpn)
    if not sub_cpn:
        return None

    # Find the transition in the subnet
    transition_in = sub_cpn.get_transition_by_name(interaction_node.a_i)
    if not transition_in:
        return None

    # Use the forward traversal function
    post_transitions = find_next_non_silent_transitions(sub_cpn, transition_in)

    # Remove the current transition itself, if present
    post_transitions = [t for t in post_transitions if t.name != transition_in.name]

    # Return one transition if exists, else None
    return post_transitions.pop() if post_transitions else None


def build_transition_net(
    current_trans: str,
    pre_trans: str = None,
    post_trans: str = None,
):
    net = PetriNet("generated_net")
    im = Marking()
    fm = Marking()

    def add_arc(src, tgt):
        arc = PetriNet.Arc(src, tgt)
        src.out_arcs.add(arc)
        tgt.in_arcs.add(arc)
        net.arcs.add(arc)

    # ---------------- Core transition ----------------
    current = PetriNet.Transition(current_trans, current_trans)
    net.transitions.add(current)

    # ---------------- Pre side ----------------
    if pre_trans is not None:
        pre = PetriNet.Transition(pre_trans, pre_trans)
        p_pre = PetriNet.Place(f"{current_trans}_pre")

        net.transitions.add(pre)
        net.places.add(p_pre)

        add_arc(pre, p_pre)
        add_arc(p_pre, current)

        p_in = PetriNet.Place(f"{pre_trans}_in")
        net.places.add(p_in)
        add_arc(p_in, pre)
        im[p_in] = 1

    else:
        p_in = PetriNet.Place(f"{current_trans}_in")
        net.places.add(p_in)
        add_arc(p_in, current)
        im[p_in] = 1

    # ---------------- Post side ----------------
    if post_trans is not None:
        p_post = PetriNet.Place(f"{current_trans}_post")
        post = PetriNet.Transition(post_trans, post_trans)

        net.places.add(p_post)
        net.transitions.add(post)

        add_arc(current, p_post)
        add_arc(p_post, post)

        p_out = PetriNet.Place(f"{post_trans}_out")
        net.places.add(p_out)
        add_arc(post, p_out)
        fm[p_out] = 1

    else:
        p_out = PetriNet.Place(f"{current_trans}_out")
        net.places.add(p_out)
        add_arc(current, p_out)
        fm[p_out] = 1

    return net, im, fm


# -------------------------------------------------
def align_interaction_node(
    hcpn: HCPN, module_name: str, interaction_node, skip_cost: int
):

    pre_transition = find_pre_transition(
        hcpn, interaction_node.v_d_s.d, interaction_node
    )
    post_transition = find_post_transition(
        hcpn, interaction_node.v_d_t.d, interaction_node
    )

    net, im, fm = build_transition_net(
        interaction_node.a_i,
        pre_transition.name if pre_transition else None,
        post_transition.name if post_transition else None,
    )

    # gviz = pn_visualizer.apply(net, im, fm)
    # pn_visualizer.save(gviz, "petri_net.png")

    event_log = build_interaction_df(interaction_node)
    alignment, cost, deviations = align_petri_net(
        event_log, net, im, fm, skip_cost, module_name
    )

    return alignment, cost, deviations


# -------------------------------------------------
def hierarchical_conformance_checking(
    event_log_tree_nodes: Set[Any], hcpn: HCPN, delta_D=1, delta_I=2
):
    consistency, total_cost, deviations = defaultdict(list), 0, defaultdict(list)

    device_nodes = [v for v in event_log_tree_nodes if hasattr(v, "V_d_E")]
    interaction_nodes = [v for v in event_log_tree_nodes if hasattr(v, "a_i")]
    # TODO: when doing conformance checking on interaction node,
    # consider the pre-events of interaction activity in d_s component
    # and post-events of interaction activity in d_t component
    max_cost = 0
    for v_d in device_nodes:
        module_name = v_d.d
        if module_name not in hcpn.modules:
            total_cost += delta_D
            deviations[module_name] = [Deviation("skip", ">>", module_name)]
            max_cost += delta_D
            continue
        align, cost, dev = align_device_node(hcpn, module_name, v_d, delta_D)
        consistency[module_name] = align
        total_cost += cost
        deviations[module_name] = dev
        max_cost +=(len(align) + len(dev)) * delta_D
    
    interaction_groups = [v for v in interaction_nodes if v.v_d_s.d == v.d_p]
    groups = defaultdict(list)
    for v in interaction_groups:
        groups[(v.v_d_s.d, v.d_p)].append(v)

    
    for (d_s, d_p), interaction_log in groups.items():
        d_t_groups = defaultdict(list)
        for v in interaction_log:
            d_t_groups[v.v_d_t.d].append(v)
        dest = "_".join(map(str, sorted(d_t_groups.keys())))

        interaction_module_name = f"I_{d_s}_{dest}"
        if interaction_module_name not in hcpn.modules:
            total_cost += delta_I
            max_cost += delta_I
            deviations[interaction_module_name] = [Deviation("skip", ">>", interaction_module_name)]
            continue
        for interaction_node in interaction_log:
            align, cost, dev = align_interaction_node(hcpn, interaction_module_name, interaction_node, delta_I)
            consistency[interaction_module_name] = align
            total_cost += cost
            deviations[interaction_module_name] = dev
            max_cost +=(len(align) + len(dev)) * delta_I

    fitness = 1 - (total_cost / max_cost)
    
    return consistency, fitness, deviations


# -------------------------------------------------
def visualize_conformance(hcpn, markings, deviations, consistency):
    viz = visualise_conformance_result(
        hcpn,
        markings,
        deviations,
        consistency,
        layout_name="klay",
        orientation="TB",
        port=8051,
        super_children_two_rows=False,  # places top, transitions bottom (same Y)
        show_tokens=False,
        module_label_font_size=80,
        supermodule_label_font_size=80,
        aggregate_to_supermodules=False,
        run=False
    )
    viz.run(layout_name="klay", orientation="TB", port=8051)


# -------------------------------------------------
if __name__ == "__main__":
    # Load event log tree
    V, _, _ = EventLog2EventLogTree("./temp_event_logs_new_clean/results/merged")

    # Build HCPN
    hcpn, markings = build_hcpn_from_event_logs("./temp_event_logs_new/results/merged")

    # Run hierarchical conformance
    consistency, fitness, deviations = hierarchical_conformance_checking(V, hcpn)

    print("Fitness:", fitness)
    print(f"Total deviations: {len(deviations)}")

    # Visualize
    viz = visualize_conformance(hcpn, markings, deviations, consistency)
    # viz.save("hcpn_conformance")
