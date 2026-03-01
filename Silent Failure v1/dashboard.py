import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import seaborn as sns
from datetime import datetime

from pipeline_simulator import load_olist_data, run_pipeline
from detection_engine import (
    run_detection, summarise_results,
    build_column_health_matrix, DEFAULT_THRESHOLDS
)

st.set_page_config(page_title="Pipeline Silent Failure Detector", page_icon="🔍", layout="wide")

st.markdown("""
<style>
    div[data-testid="stExpander"] { border: 1px solid #313244; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

STAGE_LABELS = {
    '1_ingest':    '① Ingest',
    '2_enrich':    '② Enrich',
    '3_transform': '③ Transform',
    '4_aggregate': '④ Aggregate',
    '5_output':    '⑤ Output',
}

FAILURE_DESCRIPTIONS = {
    'record_drop':       'Silently drops a fraction of rows — no error raised',
    'stale_timestamps':  'Replaces all timestamps with a fixed stale date',
    'null_flood':        'Injects NaNs into customer_state beyond normal null rate',
    'price_corruption':  'Sets ~25% of prices to 0 or negative',
    'duplicate_records': 'Silently duplicates rows — inflates counts and revenue',
    'schema_drift':      'Casts price column to string — numeric aggregations silently produce NaN',
    'canary_removal':    'Removes the synthetic canary record',
}

def severity_badge(severity, passed):
    if passed:                 return '🟢 PASS'
    if severity == 'critical': return '🔴 CRITICAL'
    if severity == 'warning':  return '🟡 WARNING'
    return '⚪ INFO'

@st.cache_data
def get_baseline():
    raw = load_olist_data(data_dir='../data')
    stages = run_pipeline(raw, failures={})
    return raw, stages


def draw_stage_health_chart(summary):
    fig, ax = plt.subplots(figsize=(10, 1.8))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')
    stages  = list(STAGE_LABELS.values())
    healths = [summary['stage_health'].get(k, {}).get('health_pct', 0) for k in STAGE_LABELS]
    colors  = ['#a6e3a1' if h == 100 else '#fab387' if h >= 60 else '#f38ba8' for h in healths]
    bars = ax.barh(stages, healths, color=colors, height=0.5, edgecolor='#313244')
    ax.set_xlim(0, 115)
    ax.set_xlabel('Health %', color='#cdd6f4', fontsize=9)
    ax.tick_params(colors='#cdd6f4', labelsize=9)
    for spine in ax.spines.values(): spine.set_color('#313244')
    for bar, h in zip(bars, healths):
        ax.text(h + 1, bar.get_y() + bar.get_height() / 2, f'{h:.0f}%', va='center', color='#cdd6f4', fontsize=9)
    ax.set_title('Stage Health Overview', color='#cdd6f4', fontsize=11, pad=8)
    plt.tight_layout()
    return fig


def draw_row_count_chart(stages, baseline_stages):
    fig, ax = plt.subplots(figsize=(8, 3))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')
    labels          = list(STAGE_LABELS.values())
    baseline_counts = [len(baseline_stages[k]) for k in STAGE_LABELS]
    actual_counts   = [len(stages[k]) for k in STAGE_LABELS]
    x, w = np.arange(len(labels)), 0.35
    ax.bar(x - w/2, baseline_counts, w, label='Baseline', color='#89b4fa', alpha=0.85)
    ax.bar(x + w/2, actual_counts,   w, label='This run', color='#f38ba8', alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, color='#cdd6f4', fontsize=8, rotation=20, ha='right')
    ax.tick_params(axis='y', colors='#cdd6f4')
    ax.set_title('Row Counts: Baseline vs This Run', color='#cdd6f4', fontsize=10)
    ax.legend(facecolor='#313244', labelcolor='#cdd6f4', fontsize=8)
    for spine in ax.spines.values(): spine.set_color('#313244')
    plt.tight_layout()
    return fig


def draw_column_health_matrix(results):
    matrix = build_column_health_matrix(results)
    if matrix.empty:
        return None

    matrix.columns = [STAGE_LABELS.get(c, c) for c in matrix.columns]

    cmap = mcolors.LinearSegmentedColormap.from_list('health', ['#f38ba8', '#fab387', '#a6e3a1'], N=256)
    cmap.set_bad('#45475a')

    fig_h = max(4, len(matrix) * 0.42 + 1.5)
    fig, ax = plt.subplots(figsize=(9, fig_h))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')

    sns.heatmap(
        matrix, ax=ax, cmap=cmap, vmin=0, vmax=1,
        linewidths=0.5, linecolor='#1e1e2e',
        annot=False, cbar=False, mask=matrix.isna(),
    )

    # Grey fill for NaN cells
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            if pd.isna(matrix.iloc[i, j]):
                ax.add_patch(plt.Rectangle((j, i), 1, 1, color='#45475a', zorder=2))

    ax.set_title(
        'Column Health Matrix   🟢 pass   🟡 warning   🔴 critical   ■ not present at this stage',
        color='#cdd6f4', fontsize=10, pad=10
    )
    ax.tick_params(colors='#cdd6f4', labelsize=8)
    ax.set_xlabel('')
    ax.set_ylabel('')
    for spine in ax.spines.values(): spine.set_color('#313244')
    plt.xticks(rotation=25, ha='right')
    plt.yticks(rotation=0)
    plt.tight_layout()
    return fig


def draw_check_type_matrix(results):
    rows = []
    for stage, checks in results.items():
        for c in checks:
            rows.append({
                'Stage': STAGE_LABELS[stage],
                'Check': c.check_name.replace('_', ' '),
                'Value': 1 if c.passed else (-1 if c.severity == 'critical' else -0.5),
            })
    df    = pd.DataFrame(rows)
    pivot = df.pivot_table(index='Check', columns='Stage', values='Value', aggfunc='min')
    fig, ax = plt.subplots(figsize=(10, max(3, len(pivot) * 0.45 + 1)))
    fig.patch.set_facecolor('#1e1e2e')
    ax.set_facecolor('#1e1e2e')
    cmap = sns.diverging_palette(10, 130, as_cmap=True)
    sns.heatmap(pivot, ax=ax, cmap=cmap, vmin=-1, vmax=1,
                linewidths=0.5, linecolor='#313244', annot=False, cbar=False)
    ax.set_title('Check Type Matrix', color='#cdd6f4', fontsize=10)
    ax.tick_params(colors='#cdd6f4', labelsize=8)
    ax.set_xlabel('')
    ax.set_ylabel('')
    for spine in ax.spines.values(): spine.set_color('#313244')
    plt.xticks(rotation=30, ha='right')
    plt.tight_layout()
    return fig


# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown('## 🧪 Failure Injection')
    st.markdown('Toggle failures to inject silently into the pipeline.')
    st.divider()

    failures = {}

    if st.toggle('🗑️ Record Drop'):
        rate = st.slider('Drop rate', 0.05, 0.50, 0.20, 0.05)
        failures['record_drop'] = rate
        st.caption(FAILURE_DESCRIPTIONS['record_drop'])
    st.divider()
    if st.toggle('🕰️ Stale Timestamps'):
        failures['stale_timestamps'] = True
        st.caption(FAILURE_DESCRIPTIONS['stale_timestamps'])
    st.divider()
    if st.toggle('🕳️ Null Flood (customer_state)'):
        rate = st.slider('Null rate', 0.10, 0.80, 0.40, 0.05)
        failures['null_flood'] = rate
        st.caption(FAILURE_DESCRIPTIONS['null_flood'])
    st.divider()
    if st.toggle('💸 Price Corruption'):
        failures['price_corruption'] = True
        st.caption(FAILURE_DESCRIPTIONS['price_corruption'])
    st.divider()
    if st.toggle('📋 Duplicate Records'):
        rate = st.slider('Duplication rate', 0.05, 0.50, 0.15, 0.05)
        failures['duplicate_records'] = rate
        st.caption(FAILURE_DESCRIPTIONS['duplicate_records'])
    st.divider()
    if st.toggle('🔤 Schema Drift (price → str)'):
        failures['schema_drift'] = True
        st.caption(FAILURE_DESCRIPTIONS['schema_drift'])
    st.divider()
    if st.toggle('🐦 Remove Canary Record'):
        failures['canary_removal'] = True
        st.caption(FAILURE_DESCRIPTIONS['canary_removal'])

    st.divider()
    run_btn = st.button('▶ Run Pipeline', type='primary', use_container_width=True)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
st.title('🔍 Silent Failure Detector')
st.markdown('*Olist e-commerce pipeline — failures pass silently, the detector catches them*')
st.divider()

raw_data, baseline_stages = get_baseline()

if 'last_results' not in st.session_state:
    st.session_state.last_results  = None
    st.session_state.last_stages   = None
    st.session_state.last_failures = {}
    st.session_state.last_summary  = None
    st.session_state.run_history   = []

if run_btn or st.session_state.last_results is None:
    with st.spinner('Running pipeline…'):
        stages  = run_pipeline(raw_data, failures=failures)
        results = run_detection(stages, baseline_stages)
        summary = summarise_results(results)

    st.session_state.last_results  = results
    st.session_state.last_stages   = stages
    st.session_state.last_failures = failures.copy()
    st.session_state.last_summary  = summary
    st.session_state.run_history.append({
        'time':     datetime.now().strftime('%H:%M:%S'),
        'failures': len(failures),
        'health_%': summary['overall_health'],
        'critical': summary['criticals'],
        'warnings': summary['warnings'],
        'checks':   summary['total_checks'],
    })

results         = st.session_state.last_results
stages          = st.session_state.last_stages
summary         = st.session_state.last_summary
active_failures = st.session_state.last_failures

# Metrics row
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric('Overall Health',  f"{summary['overall_health']}%")
c2.metric('Checks Run',      summary['total_checks'])
c3.metric('Passed',          summary['passed'])
c4.metric('🔴 Critical',     summary['criticals'])
c5.metric('🟡 Warnings',     summary['warnings'])

st.divider()

if active_failures:
    names = ', '.join(f'`{k}`' for k in active_failures)
    st.error(f'⚠️ **Failures injected (silently):** {names} — the pipeline raised no exceptions')
else:
    st.success('✅ No failures injected — clean run baseline')

st.divider()

# Charts
col_l, col_r = st.columns([1.2, 1])
with col_l: st.pyplot(draw_stage_health_chart(summary))
with col_r: st.pyplot(draw_row_count_chart(stages, baseline_stages))

st.divider()

# Check Type Matrix — always visible
st.markdown('### 🔎 Check Type Matrix')
st.markdown('Which check types fired at which stages. Green = pass, red = critical, orange = warning.')
st.pyplot(draw_check_type_matrix(results))

st.divider()

# Column Health Matrix — collapsible
with st.expander('📊 Column Health Matrix — click to expand', expanded=False):
    st.markdown('Rows = dataset columns. Columns = pipeline stages. Trace exactly where each column becomes unhealthy.')
    fig_col = draw_column_health_matrix(results)
    if fig_col:
        st.pyplot(fig_col)

st.divider()

# Stage detail
st.markdown('### Stage-by-Stage Results')

for stage_key, stage_label in STAGE_LABELS.items():
    checks     = results.get(stage_key, [])
    sh         = summary['stage_health'].get(stage_key, {})
    passed     = sh.get('passed', 0)
    total      = sh.get('total', 0)
    health_pct = sh.get('health_pct', 0)

    icon   = '🟢' if health_pct == 100 else '🟡' if health_pct >= 60 else '🔴'
    header = f'{icon} {stage_label}  —  {passed}/{total} checks passed  ({health_pct:.0f}%)'

    with st.expander(header, expanded=(health_pct < 100)):
        rc = len(stages.get(stage_key, []))
        bc = len(baseline_stages.get(stage_key, []))
        st.caption(f'Rows this run: **{rc:,}** | Baseline: **{bc:,}**')

        table_checks  = [c for c in checks if c.column is None]
        column_checks = [c for c in checks if c.column is not None]

        if table_checks:
            st.markdown('**Table-level checks**')
            for c in table_checks:
                badge = severity_badge(c.severity, c.passed)
                a, b  = st.columns([1, 3])
                with a: st.markdown(f'**{badge}**')
                with b:
                    st.markdown(c.message)
                    if not c.passed and c.expected is not None:
                        st.markdown(
                            f'<span style="color:#6c7086;font-size:0.85em;">Expected: `{c.expected}` → Got: `{c.actual}`</span>',
                            unsafe_allow_html=True,
                        )

        failed_cols = [c for c in column_checks if not c.passed]
        passed_cols = [c for c in column_checks if c.passed]

        if failed_cols:
            st.markdown('**Column-level failures**')
            for c in failed_cols:
                badge = severity_badge(c.severity, c.passed)
                a, b  = st.columns([1, 3])
                with a: st.markdown(f'**{badge}**')
                with b:
                    st.markdown(c.message)
                    if c.expected is not None:
                        st.markdown(
                            f'<span style="color:#6c7086;font-size:0.85em;">Expected: `{c.expected}` → Got: `{c.actual}`</span>',
                            unsafe_allow_html=True,
                        )

        if passed_cols:
            with st.expander(f'✅ {len(passed_cols)} column checks passed', expanded=False):
                for c in passed_cols:
                    st.markdown(f'🟢 {c.message}')

# Run history
if st.session_state.run_history:
    st.divider()
    st.markdown('### 📈 Run History')
    st.dataframe(pd.DataFrame(st.session_state.run_history), use_container_width=True, hide_index=True)

# Raw explorer
st.divider()
with st.expander('🔬 Explore Raw Stage Data'):
    sel     = st.selectbox('Select stage', list(STAGE_LABELS.keys()), format_func=lambda k: STAGE_LABELS[k])
    df_view = stages.get(sel, pd.DataFrame())
    st.markdown(f'**{len(df_view):,} rows × {len(df_view.columns)} columns**')
    st.dataframe(df_view.head(100), use_container_width=True)