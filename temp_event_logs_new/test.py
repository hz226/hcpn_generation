import os
import pandas as pd
import pm4py
from pm4py.objects.conversion.log import converter as log_converter
from pm4py.visualization.petri_net import visualizer as pn_visualizer

# -------------------------------
# 1️⃣ Configuration
# -------------------------------
folder_path = "./"
output_csv = "merged_event_log.csv"
petri_png = "petri_net.png"
TIME_GAP_SECONDS = 4

if os.path.exists(output_csv):
    os.remove(output_csv)
    print(f"Removed existing file '{output_csv}'")


# -------------------------------
# 2️⃣ Merge CSVs and transform 'a'
# -------------------------------
csv_files = [f for f in os.listdir(folder_path) if f.endswith('.csv')]
dfs = []

def combine_activity(row):
    base = str(row['a'])
    if pd.notna(row['d']) and row['d'] != '':
        return f"{base}_{row['d']}"
    elif pd.notna(row['d_p']) and row['d_p'] != '':
        return f"{base}_{row['d_p']}"
    else:
        return base

for file in csv_files:
    print(f'file= {file}')
    df = pd.read_csv(os.path.join(folder_path, file))

    # Ensure required columns exist
    for col in ['c','a','t','d','d_p','val']:
        if col not in df.columns:
            df[col] = ''

    df['a'] = df.apply(combine_activity, axis=1)
    dfs.append(df[['c','a','t','val']])

merged_df = pd.concat(dfs, ignore_index=True)

# -------------------------------
# 3️⃣ Sort and ensure valid timestamp column
# -------------------------------
merged_df['t'] = pd.to_datetime(merged_df['t'], errors='coerce')
merged_df = merged_df.dropna(subset=['t']).sort_values(by='t').reset_index(drop=True)

# -------------------------------
# 4️⃣ Reset 'c' based on time gaps
# -------------------------------
time_diff = merged_df['t'].diff().dt.total_seconds()

merged_df['c_new'] = (
    time_diff.isna() | (time_diff > TIME_GAP_SECONDS)
).cumsum()

merged_df['c'] = merged_df['c_new'].astype(int)
merged_df.drop(columns=['c_new'], inplace=True)

# -------------------------------
# Remove existing output CSV
# -------------------------------
if os.path.exists(output_csv):
    os.remove(output_csv)
    print(f"Removed existing file '{output_csv}'")

merged_df.to_csv(output_csv, index=False)
print(f"Merged {len(csv_files)} files into '{output_csv}'")

# -------------------------------
# 5️⃣ Convert to PM4Py event log
# -------------------------------
log_df = merged_df.rename(columns={
    'c':'case:concept:name',
    'a':'concept:name',
    't':'time:timestamp'
})

log = log_converter.apply(log_df)

from pm4py.algo.filtering.log.variants import variants_filter

log = variants_filter.filter_log_variants_percentage(log, 0.9)
# -------------------------------
# 6️⃣ Discover Petri net
# -------------------------------
net, initial_marking, final_marking = pm4py.discover_petri_net_inductive(
    log,
    noise_threshold=0.02,
    activity_key='concept:name',
    timestamp_key='time:timestamp',
    case_id_key='case:concept:name'
)

decorations = {}

for t in net.transitions:
    if t.label is None:  # silent transition
        decorations[t] = {
            "label": f"{t.name}@SILENT",        # keep empty label
            "color": "white"    # fill color
        }
# -------------------------------
# 8️⃣ Visualization (Reduced twisty edges)
# -------------------------------
gviz_params = {
    "format": "png",
    "layout": "dot",
    "rankdir": "TB",      # Horizontal usually cleaner
}

gviz = pn_visualizer.apply(
    net,
    initial_marking,
    final_marking,
    parameters=gviz_params,
    aggregated_statistics=decorations
)

pn_visualizer.view(gviz)
pn_visualizer.save(gviz, petri_png)

print(f"Petri net saved as '{petri_png}'")
