#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import csv
import json
import pathlib
from datetime import datetime
import pandas as pd
from typing import Tuple, List

# =========================
# CONFIG
# =========================
DEFAULT_N_REP = 10
PRESENCE_THRESHOLD = 0.6
DURATION_QUANTILE = 0.9
MIN_CASE_LENGTH = 1
ENABLE_DIVERSITY = True
DIVERSITY_MIN_FREQ = 1

RESULTS_FOLDER = "./results"

SENSOR_FIELDS = ['c_s','a_s','t','val','d','sid']
ACTUATOR_FIELDS = ['c_a','a_cmd','t','s_pre','s_post','d','id']
INTERACTION_FIELDS = ['c_i','a_i','t','m_i','d_s','d_t','d_p']

ALL_REPRESENTATIVE = {
    "sensor": SENSOR_FIELDS,
    "actuator": ACTUATOR_FIELDS,
    "interaction": INTERACTION_FIELDS
}

# =========================
# HELPER FUNCTIONS
# =========================
def safe_get(row, key):
    return row[key] if key in row and row[key] != "" else None

def derive_c(row):
    return safe_get(row, "c_s") or safe_get(row, "c_a") or safe_get(row, "c_i")

def derive_a(row):
    return safe_get(row, "a_s") or safe_get(row, "a_cmd") or safe_get(row, "a_i")

def derive_device(row):
    return safe_get(row, "d") or safe_get(row, "d_p") or "unknown"

def normalize_time(t_str):
    if not t_str:
        return None
    try:
        return datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
    except:
        return None

# =========================
# EDIT DISTANCE & LCS
# =========================
def edit_distance(a: Tuple[str,...], b: Tuple[str,...]) -> int:
    la, lb = len(a), len(b)
    dp = [[0]*(lb+1) for _ in range(la+1)]
    for i in range(la+1): dp[i][0]=i
    for j in range(lb+1): dp[0][j]=j
    for i in range(1, la+1):
        for j in range(1, lb+1):
            cost = 0 if a[i-1]==b[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[la][lb]

def lcs(seq_list: List[Tuple[str,...]]) -> List[str]:
    if not seq_list:
        return []
    def lcs_two(a,b):
        la, lb = len(a), len(b)
        dp = [[0]*(lb+1) for _ in range(la+1)]
        for i in range(1, la+1):
            for j in range(1, lb+1):
                if a[i-1]==b[j-1]:
                    dp[i][j]=dp[i-1][j-1]+1
                else:
                    dp[i][j]=max(dp[i-1][j],dp[i][j-1])
        i,j=la,lb
        out=[]
        while i>0 and j>0:
            if a[i-1]==b[j-1]:
                out.append(a[i-1]); i-=1; j-=1
            elif dp[i-1][j]>=dp[i][j-1]:
                i-=1
            else: j-=1
        return list(reversed(out))
    res=list(seq_list[0])
    for s in seq_list[1:]:
        res=lcs_two(res,s)
        if not res:
            break
    return res

# =========================
# MERGE DEVICE CSVS
# =========================
def merge_device_csvs(device_folder, output_file):
    csv_files=[f for f in os.listdir(device_folder) if f.endswith(".csv")]
    merged_rows=[]
    all_columns=set()

    for file in csv_files:
        if "merge" in file.lower(): continue
        with open(os.path.join(device_folder,file), newline='') as f:
            reader=csv.DictReader(f)
            all_columns.update(reader.fieldnames)

    all_columns.update(["c","a","device","type"])
    all_columns=list(all_columns)

    for file in csv_files:
        if "merge" in file.lower(): continue
        file_type="sensor" if "sensor" in file.lower() else "actuator" if "actuator" in file.lower() else "interaction"
        with open(os.path.join(device_folder,file), newline='') as f:
            reader=csv.DictReader(f)
            for row in reader:
                new_row={col:None for col in all_columns}
                for col in row: new_row[col]=row[col] if row[col]!="" else None
                new_row["c"]=derive_c(row)
                new_row["a"]=derive_a(row)
                new_row["device"]=derive_device(row)
                new_row["type"]=file_type
                new_row["_dt"]=normalize_time(new_row.get("t"))
                merged_rows.append(new_row)

    merged_rows.sort(key=lambda x: x["_dt"] if x["_dt"] else datetime.min)
    for r in merged_rows:
        r["t"]=r["_dt"].strftime("%Y-%m-%d %H:%M:%S") if r["_dt"] else ""
        del r["_dt"]

    with open(output_file,"w", newline="") as f:
        writer=csv.DictWriter(f, fieldnames=all_columns)
        writer.writeheader()
        writer.writerows(merged_rows)
    print("Merged →", output_file)

def merge_all_devices(root_folder):
    merged_output_folder=os.path.join(RESULTS_FOLDER,"merged")
    os.makedirs(merged_output_folder, exist_ok=True)
    for device in os.listdir(root_folder):
        device_folder=os.path.join(root_folder, device)
        if not os.path.isdir(device_folder): continue
        output_file=os.path.join(merged_output_folder,f"{device}_merged.csv")
        merge_device_csvs(device_folder, output_file)

# =========================
# REPRESENTATIVE LOGS (PM4Py)
# =========================
def generate_representative_log(input_csv, output_folder, n_rep=DEFAULT_N_REP):
    SCRIPT_DIR=pathlib.Path(output_folder)
    raw=pd.read_csv(input_csv)

    # Exit if no timestamp
    if 't' not in raw.columns:
        print(f"[WARNING] CSV {input_csv} does not contain 't' column. Skipping.")
        return None

    raw["t"]=pd.to_datetime(raw["t"], errors="coerce")
    raw=raw.dropna(subset=["t"])
    raw_orig=raw.copy()

    df=raw.rename(columns={"c":"case:concept:name","a":"concept:name","t":"time:timestamp"})
    df["case:concept:name"]=df["case:concept:name"].astype(str)
    df["concept:name"]=df["concept:name"].astype(str)
    df["time:timestamp"]=pd.to_datetime(df["time:timestamp"])
    df=df.sort_values(["case:concept:name","time:timestamp"])

    if MIN_CASE_LENGTH>1:
        size_map=df.groupby("case:concept:name").size()
        keep=size_map[size_map>=MIN_CASE_LENGTH].index
        df=df[df["case:concept:name"].isin(keep)]

    import pm4py
    from pm4py.statistics.variants.log import get as variants_get

    elog_df=pm4py.format_dataframe(df, case_id="case:concept:name", activity_key="concept:name", timestamp_key="time:timestamp")
    elog=pm4py.convert_to_event_log(elog_df)
    pm_variants=variants_get.get_variants(elog)

    variant_key_to_seq={}
    variant_key_to_cases={}
    rows_counts=[]

    for vkey,traces in pm_variants.items():
        if not traces: continue
        seq=tuple([ev["concept:name"] for ev in traces[0]])
        cases=[]
        for tr in traces:
            cid=tr.attributes.get("concept:name", None)
            if cid is None:
                tdf=pm4py.convert_to_dataframe(pm4py.EventLog([tr]))
                cid=tdf["case:concept:name"].iloc[0]
            cases.append(str(cid))
        variant_key_to_seq[vkey]=seq
        variant_key_to_cases[vkey]=cases
        rows_counts.append({"variant_key":vkey,"variant_seq":" > ".join(seq),"count":len(cases)})

    variant_counts_df=pd.DataFrame(rows_counts).sort_values("count", ascending=False)

    # Case durations
    elog_df2=pm4py.convert_to_dataframe(elog)
    elog_df2["time:timestamp"]=pd.to_datetime(elog_df2["time:timestamp"])
    case_times=elog_df2.groupby("case:concept:name")["time:timestamp"].agg(["min","max"])
    case_times["duration_sec"]=(case_times["max"]-case_times["min"]).dt.total_seconds()

    vkey_to_median_dur={}
    for k,cases in variant_key_to_cases.items():
        sub=case_times.loc[case_times.index.isin(cases)]
        vkey_to_median_dur[k]=float(sub["duration_sec"].median()) if not sub.empty else 0.0

    # Core learning
    initial_keys=list(variant_counts_df.head(n_rep)["variant_key"])
    initial_seqs=[variant_key_to_seq[k] for k in initial_keys]
    presence_count={}
    for seq in initial_seqs:
        for act in set(seq):
            presence_count[act]=presence_count.get(act,0)+1
    presence_ratio={a:presence_count[a]/len(initial_seqs) for a in presence_count}
    core_presence={a for a,r in presence_ratio.items() if r>=PRESENCE_THRESHOLD}
    lcs_spine=set(lcs(initial_seqs))
    median_values=pd.Series([vkey_to_median_dur[k] for k in initial_keys])
    duration_th=float(median_values.quantile(DURATION_QUANTILE)) if not median_values.empty else 0
    core_duration=set()
    for k in initial_keys:
        if vkey_to_median_dur[k]>=duration_th:
            core_duration.update(variant_key_to_seq[k])
    core_final=sorted(core_presence | lcs_spine | core_duration)

    # Select variants
    selected={}
    core_set=set(core_final)
    for k,seq in variant_key_to_seq.items():
        if any(a in core_set for a in seq):
            selected.setdefault(k,"core")
    if len(selected)>n_rep:
        temp=[(k,vkey_to_median_dur[k]) for k in selected]
        temp.sort(key=lambda x:x[1],reverse=True)
        selected={k:"core" for k,_ in temp[:n_rep]}
    if len(selected)<n_rep:
        for _,row in variant_counts_df.iterrows():
            k=row["variant_key"]
            if k not in selected:
                selected[k]="topK"
                if len(selected)>=n_rep: break

    # Representative cases
    representative_cases=[]
    for k in selected:
        cases=variant_key_to_cases[k]
        sub=case_times.loc[case_times.index.isin(cases)].copy()
        if sub.empty:
            rep_case=cases[0]
        else:
            med=sub["duration_sec"].median()
            sub["dist"]=(sub["duration_sec"]-med).abs()
            rep_case=sub.sort_values(["dist","duration_sec"]).index[0]
        representative_cases.append(str(rep_case))

    rep=raw_orig[raw_orig["c"].astype(str).isin(representative_cases)]
    rep=rep.sort_values(["c","t"])
    rep_path=pathlib.Path(output_folder) / "representative_event_log.csv"
    rep.to_csv(rep_path,index=False)
    return rep_path

# =========================
# SPLIT REPRESENTATIVES BY DEVICE & TYPE + COMBINED ORDERED BY T
# =========================
def split_representatives_by_device_type(rep_csv_path):
    if rep_csv_path is None:
        return

    rep_root=os.path.dirname(rep_csv_path)
    with open(rep_csv_path,newline='') as f:
        reader=csv.DictReader(f)
        rows=list(reader)

    # Group by device
    device_groups={}
    for row in rows:
        device=row.get("d") or row.get("d_p") or "unknown"
        device=str(device).strip().replace(" ","_").replace("/","_")
        if device not in device_groups:
            device_groups[device]=[]
        device_groups[device].append(row)

    for device, dev_rows in device_groups.items():
        device_folder=os.path.join(rep_root,device)
        os.makedirs(device_folder,exist_ok=True)

        type_groups={"sensor":[],"actuator":[],"interaction":[]}
        for r in dev_rows:
            t=r.get("type")
            if t in type_groups:
                type_groups[t].append(r)

        all_rows_for_device=[]
        # Write type-specific CSVs
        for ttype,trows in type_groups.items():
            if not trows: continue
            fields_map={"sensor":SENSOR_FIELDS,"actuator":ACTUATOR_FIELDS,"interaction":INTERACTION_FIELDS}
            fields=fields_map[ttype]

            out_file=os.path.join(device_folder,f"{ttype}_event_log.csv")
            with open(out_file,"w",newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields)
                writer.writeheader()
                for r in trows:
                    writer.writerow({k:r.get(k) for k in fields})
            print(f"Saved {out_file}")

            all_rows_for_device.extend(trows)

        # Write combined CSV for device, ordered by t
        if all_rows_for_device:
            all_cols=set()
            for r in all_rows_for_device:
                all_cols.update(r.keys())
            all_cols=list(all_cols)

            all_rows_for_device.sort(key=lambda r: normalize_time(r.get("t")) if r.get("t") else datetime.min)

            combined_file=os.path.join(device_folder,"representative_event_log.csv")
            with open(combined_file,"w",newline='') as f:
                writer=csv.DictWriter(f,fieldnames=all_cols)
                writer.writeheader()
                for r in all_rows_for_device:
                    writer.writerow({k:r.get(k) for k in all_cols})
            print(f"Saved combined representative CSV (ordered by t): {combined_file}")

# =========================
# PROCESS ALL DEVICES
# =========================
def process_all_devices(root_input):
    merged_folder=os.path.join(RESULTS_FOLDER,"merged")
    os.makedirs(merged_folder,exist_ok=True)

    merge_all_devices(root_input)

    for file in os.listdir(merged_folder):
        if file.endswith("_merged.csv"):
            merged_csv_path=os.path.join(merged_folder,file)
            rep_csv=generate_representative_log(merged_csv_path, merged_folder, DEFAULT_N_REP)
            split_representatives_by_device_type(rep_csv)

# =========================
# MAIN
# =========================
if __name__=="__main__":
    ROOT_FOLDER="./"
    os.makedirs(RESULTS_FOLDER,exist_ok=True)
    process_all_devices(ROOT_FOLDER)
    print("All done. Results saved under:", RESULTS_FOLDER)
