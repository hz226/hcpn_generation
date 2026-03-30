"""
Definition-faithful EventLog2EventLogTree with datetime CSV parsing
==================================================================
- Fields exactly match your definitions
- Parses timestamps like '2026-01-13 18:00:00'
- Loads from device folders: E1/, E2/, W1/
- Visualizes with Graphviz
"""

from dataclasses import dataclass
from typing import Any, Tuple, Set, Dict, List
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from graphviz import Digraph
import csv
import uuid
import json

from sympy import false

# =================================================
# Event definitions (exactly as in the paper)
# =================================================


@dataclass(frozen=True)
class SensorEventLog:
    c_s: str
    a_s: str
    t: datetime
    val: Any
    d: str
    sid: str


@dataclass(frozen=True)
class ActuationEventLog:
    c_a: str
    a_cmd: str
    t: datetime
    s_pre: Any
    s_post: Any
    d: str
    id: str


@dataclass(frozen=True)
class InteractionPayload:
    m_i: Tuple[Tuple[str, Any], ...]


@dataclass(frozen=True)
class InteractionEventLog:
    c_i: str
    a_i: str
    t: datetime
    m_i: InteractionPayload
    d_s: str
    d_t: str
    d_p: str


# =================================================
# Event log tree nodes (definition-faithful)
# =================================================


@dataclass(frozen=True)
class SensorEventNode:
    e_s: SensorEventLog


@dataclass(frozen=True)
class ActuationEventNode:
    e_a: ActuationEventLog


@dataclass(frozen=True)
class InteractionEventNode:
    e_i: InteractionEventLog


@dataclass
class DeviceComponentNode:
    d: str
    V_d_E: List[SensorEventNode]
    V_d_A: List[ActuationEventNode]
    V_d_I: List[InteractionEventNode]
    # [case_id, events] sensor, actuator, interaction events per case
    event_dict: dict[str, List]

    def __hash__(self):
        return hash(self.d)


@dataclass(frozen=True)
class InteractionNode:
    c_i: str
    a_i: str
    t: datetime
    v_d_s: DeviceComponentNode
    v_d_t: DeviceComponentNode
    d_p: str


# =================================================
# Timestamp parser
# =================================================


def parse_timestamp(ts_str: str) -> datetime:
    return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")


# =================================================
# CSV loaders
# =================================================


def load_sensor_event_logs(csv_path: Path) -> Set[SensorEventLog]:
    logs = set()
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            val = r["val"]
            try:
                val = float(val)
            except ValueError:
                pass
            logs.add(
                SensorEventLog(
                    c_s=r["c_s"],
                    a_s=r["a_s"],
                    t=parse_timestamp(r["t"]),
                    val=val,
                    d=r["d"],
                    sid=r["sid"],
                )
            )
    return logs


def load_actuation_event_logs(csv_path: Path) -> Set[ActuationEventLog]:
    logs = set()
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            logs.add(
                ActuationEventLog(
                    c_a=r["c_a"],
                    a_cmd=r["a_cmd"],
                    t=parse_timestamp(r["t"]),
                    s_pre=r["s_pre"],
                    s_post=r["s_post"],
                    d=r["d"],
                    id=r["id"],
                )
            )
    return logs


def load_interaction_event_logs(csv_path: Path) -> Set[InteractionEventLog]:
    logs = set()
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # parse payload as JSON if it exists
            raw_payload = r.get("m_i", "{}")
            try:
                payload_dict = json.loads(raw_payload)
                payload_tuple = tuple(payload_dict.items())
            except json.JSONDecodeError:
                payload_tuple = ()

            logs.add(
                InteractionEventLog(
                    c_i=r["c_i"],
                    a_i=r["a_i"],
                    t=parse_timestamp(r["t"]),
                    m_i=InteractionPayload(payload_tuple),
                    d_s=r["d_s"],
                    d_t=r["d_t"],
                    d_p=r.get("d_p"),
                )
            )
    return logs


def get_device(v):
    if hasattr(v, "d_p"):
        return v.d_p
    if hasattr(v, "d"):
        return v.d
    raise ValueError(f"Unknown event type: {type(v)}")


# =================================================
# EventLog → EventLogTree algorithm
# =================================================


def EventLog2EventLogTree(base_dir: str):
    BASE_DIR = Path(base_dir)
    E_S, E_A, E_I = set(), set(), set()

    for device_dir in BASE_DIR.iterdir():
        if not device_dir.is_dir():
            continue

        sensor_csv = device_dir / "sensor_event_log.csv"
        actuator_csv = device_dir / "actuator_event_log.csv"
        interaction_csv = device_dir / "interaction_event_log.csv"

        if sensor_csv.exists():
            E_S |= load_sensor_event_logs(sensor_csv)
        if actuator_csv.exists():
            E_A |= load_actuation_event_logs(actuator_csv)
        if interaction_csv.exists():
            E_I |= load_interaction_event_logs(interaction_csv)

    print(f"Loaded: |E_S|={len(E_S)}, |E_A|={len(E_A)}, |E_I|={len(E_I)}")

    V_E, V_A, V_I_LOG, V_D, V_I, E_T = set(), set(), set(), set(), set(), set()

    for e_s in E_S:
        V_E.add(SensorEventNode(e_s))

    for e_a in E_A:
        V_A.add(ActuationEventNode(e_a))

    for e_i_log in E_I:
        V_I_LOG.add(InteractionEventNode(e_i_log))

    sensors, actuators, interactions = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    case_events = defaultdict(list)

    for v in V_E:
        sensors[v.e_s.d].append(v)
        case_events[v.e_s.c_s].append(v.e_s)
    for v in V_A:
        actuators[v.e_a.d].append(v)
        case_events[v.e_a.c_a].append(v.e_a)

    for v in V_I_LOG:
        interactions[v.e_i.d_p].append(v)
        case_events[v.e_i.c_i].append(v.e_i)

    for cid, events in case_events.items():
        events.sort(key=lambda v: v.t)

    device_nodes: Dict[str, DeviceComponentNode] = {}

    for d in set(sensors) | set(actuators):
        dev_events = {
            cid: [event for event in events if get_device(event) == d]
            for cid, events in case_events.items()
            if any(get_device(event) == d for event in events)
        }
        v_d = DeviceComponentNode(
            d=d,
            V_d_E=sorted(sensors.get(d, []), key=lambda v: v.e_s.t),
            V_d_A=sorted(actuators.get(d, []), key=lambda v: v.e_a.t),
            V_d_I=sorted(interactions.get(d, []), key=lambda v: v.e_i.t),
            event_dict={cid: dev_events[cid] for cid in dev_events},
        )
        V_D.add(v_d)
        device_nodes[d] = v_d
        for v in v_d.V_d_E + v_d.V_d_A + v_d.V_d_I:
            E_T.add((v_d, v))

    for e_i in E_I:
        v_i = InteractionNode(
            c_i=e_i.c_i,
            a_i=e_i.a_i,
            t=e_i.t,
            v_d_s=device_nodes[e_i.d_s],
            v_d_t=device_nodes[e_i.d_t],
            d_p=e_i.d_p,
        )
        V_I.add(v_i)
        E_T.update({(v_i, device_nodes[e_i.d_s]), (v_i, device_nodes[e_i.d_t])})

    return V_E | V_A | V_I_LOG | V_D | V_I, E_T, V_I


def get_timestamp(v):
    if isinstance(v, SensorEventNode):
        return v.e_s.t
    elif isinstance(v, ActuationEventNode):
        return v.e_a.t
    elif isinstance(v, InteractionEventNode):
        return v.e_i.t
    else:
        return datetime.min


ids = {}


def nid(x):
    if x not in ids:
        ids[x] = str(uuid.uuid4())
    return ids[x]


def visualize_device_component_node(dot: Digraph, v: DeviceComponentNode, device_id: str):
    dot.node(device_id, f"Device d = {v.d}", shape="box")

    # Combine all events
    all_events = list(v.V_d_E) + list(v.V_d_A) + list(v.V_d_I)

    # Helper: get case id per event
    def get_case_id(event):
        if isinstance(event, SensorEventNode):
            return event.e_s.c_s
        elif isinstance(event, ActuationEventNode):
            return event.e_a.c_a
        elif isinstance(event, InteractionEventNode):
            return event.e_i.c_i
        else:
            return None

    # Group events by case id
    case_groups = {}
    for event in all_events:
        case_id = get_case_id(event)
        if case_id not in case_groups:
            case_groups[case_id] = []
        case_groups[case_id].append(event)

    # Sort events within each case by timestamp
    for case_id, events in case_groups.items():
        events.sort(key=get_timestamp)

    # Create subtrees per case
    for case_id, events in case_groups.items():
        # Create a node representing the case
        case_node_id = f"{device_id}_case_{case_id}"
        dot.node(case_node_id, f"Case {case_id}", shape="folder", color="purple")

        # Connect device -> case
        dot.edge(device_id, case_node_id)

        # Connect events in hierarchy
        prev_item_id = None
        for item in events:
            item_id = nid(item)
            # Create event node
            if isinstance(item, SensorEventNode):
                e = item.e_s
                dot.node(item_id, f"Sensor sid={e.a_s}\nt={e.t}\nval={e.val}", shape="ellipse", color="blue")
            elif isinstance(item, ActuationEventNode):
                e = item.e_a
                dot.node(item_id, f"Actuator id={e.a_cmd}\nt={e.t}\n{e.s_pre}→{e.s_post}", shape="ellipse", color="green")
            elif isinstance(item, InteractionEventNode):
                e = item.e_i
                dot.node(item_id, f"Interaction a_i={e.a_i}\nt={e.t}\nd_s={e.d_s}\nd_t={e.d_t}", shape="ellipse", color="orange")

            # Connect hierarchy
            if prev_item_id is None:
                dot.edge(case_node_id, item_id)
            else:
                dot.edge(prev_item_id, item_id)
            prev_item_id = item_id

    return device_id



# =================================================
# Graphviz visualization
# =================================================


def visualize_event_log_tree(tree_root, filename="event_log_tree"):
    dot = Digraph(format="png")
    dot.attr(rankdir="TB")
    device_nodes_done = set()
    interaction_done = set()

    for v in tree_root:
        if not isinstance(v, InteractionNode):
            raise ValueError("The root of the tree must be a InteractionNode")
        if any(
            i.a_i == v.a_i and i.v_d_s.d == v.v_d_s.d and i.v_d_t.d == v.v_d_t.d
            for i in interaction_done
        ):
            continue
        interaction_id = nid(v)
        dot.node(
            interaction_id,
            f"interaction\nactivity={v.a_i}\ndevice {v.v_d_s.d} and {v.v_d_t.d}",
            shape="diamond",
            color="red",
        )
        interaction_done.add(v)
        d_s_id = nid(v.v_d_s)
        d_t_id = nid(v.v_d_t)
        if v.v_d_s not in device_nodes_done:
            visualize_device_component_node(dot, v.v_d_s, d_s_id)
            device_nodes_done.add(v.v_d_s)
        if v.v_d_t not in device_nodes_done:
            visualize_device_component_node(dot, v.v_d_t, d_t_id)
            device_nodes_done.add(v.v_d_t)
        
        dot.edge(interaction_id, d_s_id)
        dot.edge(interaction_id, d_t_id)

    dot.render(filename, cleanup=True)


# =================================================
# Main execution
# =================================================

if __name__ == "__main__":
    enable_debug = False  # Set to True to enable debug execution
    if not enable_debug:
        exit(0)
    V, E_T, V_I = EventLog2EventLogTree("./temp_event_logs_new_clean/results/merged")
    print(f"Constructed Event Log Tree: |V|={len(V)}, |E_T|={len(E_T)}")

    visualize_event_log_tree(V_I, "event_log_tree")
    print("✔ Event Log Tree rendered as event_log_tree.png")
