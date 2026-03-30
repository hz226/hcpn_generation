import os
from pathlib import Path
import numpy as np
import pandas as pd
from typing import Dict, Tuple
import sys

from cpn_merge import merge_sub_pages, transform_to_hcpn

sys.path.append(r"./cpn-py")

from Visualizer import HCPNCytoscapeVisualizer
from cpnpy.discovery.traditional import apply
from cpnpy.cpn.cpn_imp import CPN, EvaluationContext
from cpnpy.hcpn.hcpn_imp import HCPN
from cpnpy.visualization.hcpn import HCPNGraphViz
from cpnpy.visualization.visualizer import CPNGraphViz
from cpnpy.cpn import exporter
from cpnpy.util.conversion import json_to_cpn_xml

# ============================================================
# PARAMETERS
# ============================================================

cpn_parameters = {
    "enable_guards_discovery": True,
    "enable_timing_discovery": False,
    "noise_threshold": 0.2,
}


# ============================================================
# CSV LOADING + NORMALIZATION
# ============================================================


def load_and_normalize_csv(path: str, log_type: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    rename_map = {"t": "time:timestamp"}

    if log_type == "sensor":
        rename_map.update({"c_s": "case:concept:name", "a_s": "concept:name"})
    elif log_type == "actuator":
        rename_map.update({"c_a": "case:concept:name", "a_cmd": "concept:name"})
    elif log_type == "interaction":
        rename_map.update({"c_i": "case:concept:name", "a_i": "concept:name"})

    df = df.rename(columns=rename_map)
    df["time:timestamp"] = pd.to_datetime(df["time:timestamp"])
    df["case:concept:name"] = df["case:concept:name"].astype(str).str.strip()

    return df


def load_device_logs(
    device_folder: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sensor = load_and_normalize_csv(
        os.path.join(device_folder, "sensor_event_log.csv"), "sensor"
    )
    actuator = load_and_normalize_csv(
        os.path.join(device_folder, "actuator_event_log.csv"), "actuator"
    )
    interaction = load_and_normalize_csv(
        os.path.join(device_folder, "interaction_event_log.csv"), "interaction"
    )
    return sensor, actuator, interaction


# ============================================================
# DISCOVERY
# ============================================================


def discover_device_cpn(
    sensor_log: pd.DataFrame, actuator_log: pd.DataFrame, interaction_log: pd.DataFrame
) -> Tuple[CPN, object, dict]:

    merged_log = pd.concat(
        [sensor_log, actuator_log, interaction_log], ignore_index=True
    )
    merged_log = merged_log.sort_values(
        ["case:concept:name", "time:timestamp"]
    ).reset_index(drop=True)

    cpn_d, marking_d, eva =  apply(merged_log, parameters=cpn_parameters)
    cpn_d = remove_loop(cpn_d)
    return cpn_d, marking_d, eva

def remove_loop(cpn: CPN):
    place_list = [arc.target.name for arc in cpn.arcs if "loop" in arc.source.name]
    if not place_list:
        return cpn
    slient = "silent@skip"
    arc_list = [arc for arc in cpn.arcs if slient in arc.source.name.lower() or slient in arc.target.name.lower()]
    trans_to_remove = []

    # Remove transitions connected to loop places
    for arc in arc_list[:]:  # iterate over a copy to safely remove
        if arc.target.name in place_list:
            if arc.source not in trans_to_remove:
                trans_to_remove.append(arc.source)
                if arc.source in cpn.transitions:
                    cpn.transitions.remove(arc.source)
            if arc in cpn.arcs:
                cpn.arcs.remove(arc)

    # Remove arcs targeting removed transitions
    for arc in arc_list[:]:
        if arc.target in trans_to_remove and arc in cpn.arcs:
            cpn.arcs.remove(arc)
    return cpn


def discover_interaction_cpn(interaction_log: pd.DataFrame) -> Tuple[CPN, object, dict]:
    interaction_log = interaction_log.sort_values(
        ["case:concept:name", "time:timestamp"]
    ).reset_index(drop=True)

    return apply(interaction_log, parameters=cpn_parameters)


# ============================================================
# INTERACTION LOG CONSTRUCTION
# ============================================================


def construct_interaction(i_logs) -> pd.DataFrame:
    interaction_log = i_logs.sort_values(
        ["case:concept:name", "time:timestamp"]
    ).reset_index(drop=True)

    all_rows = []
    last_timestamp = None
    case_id = 1

    for _, row in interaction_log.iterrows():
        row = row.copy(deep=True)
        row["case:concept:name"] = f"{case_id}"
        case_id += 1

        base_time = row["time:timestamp"]
        if last_timestamp is not None and base_time <= last_timestamp:
            base_time = last_timestamp + pd.Timedelta(seconds=2)

        # source
        src = row.copy(deep=True)
        src["concept:name"] = src["d_s"]
        src["time:timestamp"] = base_time - pd.Timedelta(seconds=1)
        src["interaction_role"] = "source"

        # interaction
        mid = row.copy(deep=True)
        mid["concept:name"] = (
            f"{row['concept:name']}"  # TODO interaction node's activity name
        )
        mid["time:timestamp"] = base_time
        mid["interaction_role"] = "interaction"

        # target
        tgt = row.copy(deep=True)
        tgt["concept:name"] = row["d_t"]
        tgt["time:timestamp"] = base_time + pd.Timedelta(seconds=1)
        tgt["interaction_role"] = "target"

        all_rows.extend([src, mid, tgt])
        last_timestamp = tgt["time:timestamp"]

    df = pd.DataFrame(all_rows)
    df["concept:name"] = df["concept:name"].astype(str).str.strip()
    return df


# ============================================================
# SUBSTITUTION TRANSITION SELECTION
# ============================================================


def select_substitution_transition(cpn: CPN, device: str) -> str:
    for t in cpn.transitions:
        # if t.name.startswith(device + "_") or t.name.endswith("_" + device):
        if t.name == device:
            return t.name
    raise ValueError(f"No substitution transition found for device {device}")


# ============================================================
# COLLECT ALL INTERACTIONS
# ============================================================


def collect_all_interactions(interaction_log_dic) -> pd.DataFrame:
    logs = []
    for device, i_logs in interaction_log_dic.items():
        interaction_log = construct_interaction(i_logs)
        if not interaction_log.empty:
            logs.append(interaction_log)

    if not logs:
        return pd.DataFrame()

    return pd.concat(logs, ignore_index=True)


# ============================================================
# BUILD HCPN
# ============================================================


def build_hcpn_from_event_logs(root_folder: str) -> Tuple[HCPN, Dict[str, object]]:
    hcpn = HCPN()
    markings_dict = {}
    interaction_log_dic = {}
    device_modules = {}
    # ---------------------------
    # Step 1: Device CPNs
    # ---------------------------
    for device in os.listdir(root_folder):
        device_path = os.path.join(root_folder, device)
        if not os.path.isdir(device_path):
            continue

        sensor_log, actuator_log, interaction_log = load_device_logs(device_path)
        interaction_log_dic[device] = interaction_log
        cpn_d, marking_d, _ = discover_device_cpn(
            sensor_log, actuator_log, interaction_log
        )
        device_modules[device] = cpn_d
        markings_dict[device] = marking_d

    all_interactions = collect_all_interactions(interaction_log_dic)
    all_interactions = all_interactions[
        all_interactions["d_s"] == all_interactions["d_p"]
    ]
    grouped = all_interactions.groupby(["d_s", "d_p"])

    module_done = {}

    for d_s, d_p in grouped.groups.keys():
        interaction_log = grouped.get_group((d_s, d_p))
        interaction_cpn, marking_i, _ = discover_interaction_cpn(interaction_log)
        dest = "_".join(map(str, interaction_log.groupby("d_t").groups.keys()))
        interaction_module_name = f"I_{d_s}_{dest}"
        hcpn.add_module(interaction_module_name, interaction_cpn)
        markings_dict[interaction_module_name] = marking_i

        # substitution (structural, once)
        if d_p not in module_done:
            hcpn.add_module(d_p, device_modules[d_p])
            module_done[d_p] = True

        t_s = select_substitution_transition(interaction_cpn, d_p)
        hcpn.add_substitution(interaction_module_name, t_s, d_p)
        sub_groups = interaction_log.groupby(["d_t"])
        for d_t in sub_groups.groups.keys():
            if d_t not in module_done:
                hcpn.add_module(d_t, device_modules[d_t])
                module_done[d_t] = True
            if d_s != d_t:
                t_t = select_substitution_transition(interaction_cpn, d_t)
                hcpn.add_substitution(interaction_module_name, t_t, d_t)
    return hcpn, markings_dict


def export_to_cpn(cpn, marking, folder, module_name, counter_start):
    json_path = folder + module_name + ".json"
    xml_path = folder + module_name + ".cpn"
    context = EvaluationContext()
    exporter.export_cpn_to_json(cpn, marking, context, json_path)

    xml, new_counter = json_to_cpn_xml.apply(json_path, "myNet", counter_start)

    F = open(xml_path, "w")
    F.write(xml)
    F.close()
    return new_counter


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    enable_debug = True  # Set to True to enable debug execution
    hcpn_vis = False
    individual_cpns = True
    if enable_debug:
        EVENT_LOG_ROOT = "temp_event_logs_new/results/merged"
        file_postfix = "png"
        hierarchical_file = "my_hcpn_hierarchy"
        hcpn, markings_dict = build_hcpn_from_event_logs(EVENT_LOG_ROOT)

        if hcpn_vis:
            viz = HCPNCytoscapeVisualizer().apply(
                hcpn,
                markings_dict,
                params={
                    "show_tokens": False,
                    "module_name_is_super": lambda n: n.startswith("I_"),
                    "super_children_two_rows": False,  # Places aligned on top row; transitions on second row
                },
            )

            viz.run(layout_name="klay", orientation="TB", port=8051)
    if individual_cpns:
        cpn_folder = "cpn_new1/"
        counter_start = 100
        for module_name, module_cpn in hcpn.modules.items():
            counter_start = export_to_cpn(
                module_cpn, markings_dict.get(module_name), cpn_folder, module_name,counter_start
            )
            # every CPN module has different starting node ID
            counter_start +=10
        base_dir = Path(cpn_folder)
        cpn_array = [p.name.replace(".cpn", "") for p in base_dir.glob("I_*.cpn")]
        for inter_cpn in cpn_array:
            module_list = inter_cpn.replace("I_", "").split("_")
            resulting_cpn = f"{cpn_folder}_{inter_cpn}.cpn"
            temp_output = f"{cpn_folder}{module_list[0]}.cpn" if len(module_list) > 0 else ""
            module_list.append(f"{inter_cpn}")
            for i in range(1, len(module_list)):
                # Prerequisite: each CPN module has different node ID, otherwise, errors like repeated node ID will occur
                merge_sub_pages(temp_output, f"{cpn_folder}{module_list[i]}.cpn", resulting_cpn)
                temp_output = resulting_cpn

            transform_to_hcpn(resulting_cpn, inter_cpn, counter_start, module_list)
