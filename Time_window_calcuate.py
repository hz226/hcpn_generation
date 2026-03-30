import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from sklearn.cluster import KMeans

# ----------------------------
# Step 1: Load CSV and determine device
# ----------------------------
csv_file = 'bridge_traffic_simulation_noisy.csv'
df = pd.read_csv(csv_file)

df['device'] = df['d'].fillna(df['d_p'])
df['t'] = pd.to_datetime(df['t'], errors='coerce')
df = df.dropna(subset=['device','t']).sort_values('t').reset_index(drop=True)

# ----------------------------
# Step 2: Compute global time gaps
# ----------------------------
df['time_gap'] = df['t'].diff().dt.total_seconds()
df = df.dropna(subset=['time_gap'])
df = df[df['time_gap'] > 0].reset_index(drop=True)

# Log-transform gaps for clustering
log_gaps = np.log(df['time_gap'].values).reshape(-1,1)

# ----------------------------
# Step 3: Global K-Means clustering
# ----------------------------
n_clusters = 5
kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
df['cluster'] = kmeans.fit_predict(log_gaps)

centers_log = kmeans.cluster_centers_.flatten()
cluster_sizes = df['cluster'].value_counts().sort_index()
total_points = len(df)

# ----------------------------
# Step 4: Compute bin percentages for marker sizing
# ----------------------------
n_bins = 50
counts, bin_edges = np.histogram(log_gaps.flatten(), bins=n_bins)
bin_percentages = counts / counts.sum() * 100.0
bin_indices = np.digitize(log_gaps.flatten(), bins=bin_edges) - 1
bin_indices = np.clip(bin_indices, 0, len(counts)-1)
percentages = bin_percentages[bin_indices]

min_size, max_size = 10, 60
pct_min, pct_max = percentages.min(), percentages.max()
if not np.isclose(pct_max, pct_min):
    size_norm = min_size + ((percentages - pct_min)/(pct_max - pct_min))*(max_size - min_size)
else:
    size_norm = np.full_like(percentages, (min_size+max_size)/2.0)

df['pct'] = percentages
df['size'] = size_norm

# ----------------------------
# Step 5: Compute Top 90% band
# ----------------------------
sorted_pcts = np.sort(bin_percentages)[::-1]
cum = np.cumsum(sorted_pcts)
percents = 90
idx_90 = np.searchsorted(cum, percents, side='left')
y_thresh = sorted_pcts[idx_90] if idx_90 < len(sorted_pcts) else 0.0
y_max = float(np.nanmax(df['pct'])) if len(df) else 0.0

# ----------------------------
# Step 6: Build Plotly figure
# ----------------------------
fig = go.Figure()
colors = px.colors.qualitative.Plotly

hovertemplate = (
    'Device: %{customdata[0]}<br>'
    'Time gap: %{customdata[1]:.2f}s<br>'
    'Log(Time gap): %{customdata[2]:.2f}<br>'
    'Bin share: %{customdata[3]:.2f}%<br>'
    'Cluster: %{customdata[4]}<extra></extra>'
)

unique_clusters = df['cluster'].unique()
for cl in sorted(unique_clusters):
    cluster_df = df[df['cluster'] == cl]
    
    pct_cluster = cluster_sizes[cl]/total_points*100
    legend_label = f'Cluster {cl} (n={cluster_sizes[cl]}, {pct_cluster:.1f}%)'
    
    fig.add_trace(go.Scatter(
        x=np.log(cluster_df['time_gap']),
        y=cluster_df['pct'],
        mode='markers',
        marker=dict(
            color=colors[cl % len(colors)],
            size=cluster_df['size'],
            opacity=0.8,
            line=dict(width=0.5, color='rgba(0,0,0,0.2)')
        ),
        name=legend_label,
        customdata=np.column_stack([
            cluster_df['device'],
            cluster_df['time_gap'],
            np.log(cluster_df['time_gap']),
            cluster_df['pct'],
            cluster_df['cluster']
        ]),
        hovertemplate=hovertemplate
    ))

# ----------------------------
# Step 7: Fade below threshold points
# ----------------------------
below_mask = df['pct'] < y_thresh
if below_mask.any():
    fig.add_trace(go.Scatter(
        x=np.log(df['time_gap'][below_mask]),
        y=df['pct'][below_mask],
        mode='markers',
        marker=dict(
            color='rgba(128,128,128,0.25)',
            size=df['size'][below_mask],
            line=dict(width=0)
        ),
        showlegend=False,
        hoverinfo='skip'
    ))

# ----------------------------
# Step 8: Add horizontal band
# ----------------------------
fig.add_hrect(
    y0=y_thresh, y1=y_max,
    fillcolor='gold', opacity=0.18,
    line_width=0, layer='below'
)

# ----------------------------
# Step 9: Optional: cluster center lines
# ----------------------------
for cl, cx in enumerate(centers_log):
    fig.add_vline(
        x=cx,
        line_color=colors[cl % len(colors)],
        line_dash='dash',
        opacity=0.5
    )

# ----------------------------
# Step 10: Layout
# ----------------------------
fig.update_layout(
    title=f'Global Time Gap Clusters — Top {percents}% band',
    xaxis_title='Log(Time gap in seconds)',
    yaxis_title='Percentage of total time gaps (%)',
    hovermode='closest',
    height=720,
    template='plotly_white',
    legend_title='Clusters (size & share)'
)

fig.update_xaxes(showgrid=True, gridcolor='rgba(0,0,0,0.1)')
fig.update_yaxes(showgrid=True, gridcolor='rgba(0,0,0,0.1)')

fig.show()
