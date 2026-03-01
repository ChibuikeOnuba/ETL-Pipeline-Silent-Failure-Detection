import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Any

# ──────────────────────────────────────────────
# Result primitive
# ──────────────────────────────────────────────

@dataclass
class CheckResult:
    check_name: str
    stage: str
    passed: bool
    severity: str          # 'info' | 'warning' | 'critical'
    message: str
    column: str = None     # which column this check is about (None = table-level)
    expected: Any = None
    actual: Any = None
    details: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# Column classification
# ──────────────────────────────────────────────

# Columns that are pure identifiers — checking their distribution is meaningless
ID_COLUMNS = {
    'order_id', 'customer_id', 'seller_id', 'product_id',
    'review_id', 'customer_unique_id',
}

# Columns we know are datetimes even if dtype doesn't reflect it
DATETIME_COLUMNS = {
    'order_purchase_timestamp',
    'order_approved_at',
    'order_delivered_carrier_date',
    'order_delivered_customer_date',
    'order_estimated_delivery_date',
    'review_creation_date',
    'review_answer_timestamp',
    'shipping_limit_date',
}

def classify_columns(df: pd.DataFrame) -> dict:
    """
    Classify every column in a dataframe into one of four types:
    - 'id'          : identifier column, skip all checks
    - 'datetime'    : timestamp column, run freshness check
    - 'numeric'     : numeric column, run distribution + null checks
    - 'categorical' : string/object column, run null + category drift checks
    """
    classification = {}
    for col in df.columns:
        if col in ID_COLUMNS:
            classification[col] = 'id'
        elif col in DATETIME_COLUMNS:
            classification[col] = 'datetime'
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            classification[col] = 'datetime'
        elif pd.api.types.is_numeric_dtype(df[col]):
            classification[col] = 'numeric'
        else:
            if any(kw in col.lower() for kw in ['timestamp', 'date', 'time']):
                classification[col] = 'datetime'
            else:
                classification[col] = 'categorical'
    return classification


# ──────────────────────────────────────────────
# Thresholds
# ──────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    'row_drop_threshold':   0.10,
    'row_spike_threshold':  0.20,
    'null_rate_threshold':  0.10,
    'mean_drift_tolerance': 0.30,
    'leakage_tolerance':    0.05,
    'stale_year_threshold': 2018,
}

# Per-column null rate overrides — some columns naturally have more nulls
COLUMN_NULL_OVERRIDES = {
    'review_score':         0.25,
    'review_creation_date': 0.25,
    'order_approved_at':    0.05,
    'delivery_days':        0.15,
    'is_late':              0.15,
    'avg_review_score':     0.25,
    'late_delivery_rate':   0.15,
    'avg_delivery_days':    0.15,
    'review_comment_title':   0.90,  
    'review_comment_message': 0.60,
}


# ──────────────────────────────────────────────
# Individual check functions
# ──────────────────────────────────────────────

def check_row_count(df, stage_name, baseline_count, thresholds=None):
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    actual      = len(df)
    drop_ratio  = (baseline_count - actual) / baseline_count if baseline_count > 0 else 0
    spike_ratio = (actual - baseline_count) / baseline_count if baseline_count > 0 else 0

    if drop_ratio > t['row_drop_threshold']:
        pct = drop_ratio * 100
        return CheckResult(
            check_name='row_count_drop', stage=stage_name, passed=False,
            severity='critical' if drop_ratio > 0.20 else 'warning',
            message=f'Row count dropped {pct:.1f}% from baseline ({baseline_count} → {actual})',
            expected=baseline_count, actual=actual,
            details={'drop_pct': round(pct, 2)},
        )
    elif spike_ratio > t['row_spike_threshold']:
        pct = spike_ratio * 100
        return CheckResult(
            check_name='row_count_spike', stage=stage_name, passed=False,
            severity='warning',
            message=f'Row count spiked {pct:.1f}% above baseline ({baseline_count} → {actual}) — possible duplicates',
            expected=baseline_count, actual=actual,
            details={'spike_pct': round(pct, 2)},
        )
    return CheckResult(
        check_name='row_count', stage=stage_name, passed=True, severity='info',
        message=f'Row count OK: {actual} rows (baseline {baseline_count})',
        expected=baseline_count, actual=actual,
    )


def check_null_rate(df, stage_name, col, max_null_rate=None, thresholds=None):
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if max_null_rate is None:
        max_null_rate = COLUMN_NULL_OVERRIDES.get(col, t['null_rate_threshold'])

    if col not in df.columns:
        return CheckResult(
            check_name='null_rate', stage=stage_name, passed=False,
            severity='critical', column=col,
            message=f'Column "{col}" missing entirely from stage output',
            expected='column present', actual='column missing',
        )
    null_rate = df[col].isna().mean()
    passed    = null_rate <= max_null_rate
    return CheckResult(
        check_name='null_rate', stage=stage_name, passed=passed, column=col,
        severity='warning' if not passed else 'info',
        message=f'Null rate for "{col}": {null_rate:.1%} (threshold {max_null_rate:.0%})',
        expected=f'<= {max_null_rate:.0%}', actual=f'{null_rate:.1%}',
        details={'null_rate': round(float(null_rate), 4)},
    )


def check_value_distribution(df, stage_name, col, expected_mean, thresholds=None):
    t             = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    mean_tolerance = t['mean_drift_tolerance']

    if col not in df.columns:
        return CheckResult(
            check_name='distribution', stage=stage_name, passed=False,
            severity='critical', column=col,
            message=f'Column "{col}" missing for distribution check',
            expected='column present', actual='column missing',
        )

    numeric = pd.to_numeric(df[col], errors='coerce')

    if numeric.isna().all():
        return CheckResult(
            check_name='distribution', stage=stage_name, passed=False,
            severity='critical', column=col,
            message=f'Column "{col}" is entirely non-numeric — schema drift suspected',
            expected=f'mean ≈ {expected_mean:.2f}', actual='NaN',
        )

    actual_mean   = float(numeric.mean())
    actual_min    = float(numeric.min())
    mean_drift    = abs(actual_mean - expected_mean) / (abs(expected_mean) + 1e-9)
    has_negatives = actual_min < 0

    issues = []
    if mean_drift > mean_tolerance:
        issues.append(f'mean drifted {mean_drift:.0%} from expected ({expected_mean:.2f} → {actual_mean:.2f})')
    if has_negatives:
        issues.append(f'negative values present (min={actual_min:.2f})')

    passed   = len(issues) == 0
    severity = 'critical' if has_negatives else ('warning' if issues else 'info')
    message  = f'Distribution "{col}": ' + ('; '.join(issues) if issues else f'OK (mean={actual_mean:.2f})')

    return CheckResult(
        check_name='distribution', stage=stage_name, passed=passed,
        severity=severity, column=col,
        message=message,
        expected=f'mean ≈ {expected_mean:.2f}, min >= 0',
        actual=f'mean={actual_mean:.2f}, min={actual_min:.2f}',
        details={'actual_mean': round(actual_mean, 2), 'actual_min': round(actual_min, 2)},
    )


def check_categorical_health(df, stage_name, col, baseline_df, thresholds=None):
    """Check null rate and category drift for categorical columns."""
    t             = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    max_null_rate = COLUMN_NULL_OVERRIDES.get(col, t['null_rate_threshold'])

    if col not in df.columns:
        return CheckResult(
            check_name='categorical_health', stage=stage_name, passed=False,
            severity='critical', column=col,
            message=f'Column "{col}" missing from stage output',
            expected='column present', actual='column missing',
        )

    null_rate = df[col].isna().mean()
    if null_rate > max_null_rate:
        return CheckResult(
            check_name='categorical_health', stage=stage_name, passed=False,
            severity='warning', column=col,
            message=f'Null rate for "{col}": {null_rate:.1%} (threshold {max_null_rate:.0%})',
            expected=f'<= {max_null_rate:.0%}', actual=f'{null_rate:.1%}',
            details={'null_rate': round(float(null_rate), 4)},
        )

    # Category drift — new values not seen in baseline
    if col in baseline_df.columns:
        baseline_cats = set(baseline_df[col].dropna().unique())
        current_cats  = set(df[col].dropna().unique())
        new_cats      = current_cats - baseline_cats
        if new_cats:
            return CheckResult(
                check_name='categorical_health', stage=stage_name, passed=False,
                severity='warning', column=col,
                message=f'New categories in "{col}" not seen in baseline: {new_cats}',
                expected=f'{len(baseline_cats)} known categories',
                actual=f'{len(current_cats)} categories ({len(new_cats)} new)',
            )

    return CheckResult(
        check_name='categorical_health', stage=stage_name, passed=True,
        severity='info', column=col,
        message=f'Categorical "{col}" OK (null rate {null_rate:.1%})',
        expected=f'<= {max_null_rate:.0%} nulls', actual=f'{null_rate:.1%}',
    )


def check_timestamp_freshness(df, stage_name, col, thresholds=None):
    t          = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    stale_year = int(t['stale_year_threshold'])

    if col not in df.columns:
        return CheckResult(
            check_name='freshness', stage=stage_name, passed=False,
            severity='warning', column=col,
            message=f'Column "{col}" missing for freshness check',
            expected='column present', actual='column missing',
        )
    try:
        ts = pd.to_datetime(df[col], errors='coerce')
        if ts.isna().all():
            return CheckResult(
                check_name='freshness', stage=stage_name, passed=False,
                severity='warning', column=col,
                message=f'All values in "{col}" are unparseable as timestamps',
                expected='parseable datetimes', actual='all NaT',
            )

        all_same = ts.nunique() == 1
        max_year = int(ts.dt.year.max())
        min_year = int(ts.dt.year.min())

        if all_same:
            return CheckResult(
                check_name='freshness', stage=stage_name, passed=False,
                severity='critical', column=col,
                message=f'All timestamps in "{col}" identical — stale/cached data suspected ({ts.iloc[0]})',
                expected='varied timestamps', actual=f'all = {ts.iloc[0]}',
            )
        if max_year < stale_year:
            return CheckResult(
                check_name='freshness', stage=stage_name, passed=False,
                severity='warning', column=col,
                message=f'Timestamps in "{col}" max year is {max_year} — data may be stale',
                expected=f'>= {stale_year}', actual=str(max_year),
            )
    except Exception as e:
        return CheckResult(
            check_name='freshness', stage=stage_name, passed=False,
            severity='warning', column=col,
            message=f'Could not parse timestamps in "{col}": {e}',
            expected='parseable datetime', actual='unparseable',
        )

    return CheckResult(
        check_name='freshness', stage=stage_name, passed=True,
        severity='info', column=col,
        message=f'Timestamps in "{col}" look fresh (range: {min_year}–{max_year})',
        expected=f'>= {stale_year}', actual=str(max_year),
    )


def check_canary(df, stage_name, canary_id='ORD_CANARY_001', id_col='order_id'):
    if id_col not in df.columns:
        return CheckResult(
            check_name='canary_record', stage=stage_name, passed=False,
            severity='critical',
            message=f'Cannot check canary — id column "{id_col}" not present',
            expected='canary present', actual='id column missing',
        )
    present = canary_id in df[id_col].values
    return CheckResult(
        check_name='canary_record', stage=stage_name, passed=present,
        severity='critical' if not present else 'info',
        message=f'Canary record "{canary_id}" {"found ✓" if present else "MISSING — silently dropped!"}',
        expected='present', actual='present' if present else 'missing',
    )


def check_cross_stage_leakage(upstream_df, downstream_df, stage_name, join_col='order_id', thresholds=None):
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    tolerance = t['leakage_tolerance']

    if join_col not in upstream_df.columns or join_col not in downstream_df.columns:
        return CheckResult(
            check_name='cross_stage_id_leakage', stage=stage_name, passed=False,
            severity='warning',
            message=f'Cannot check cross-stage leakage — "{join_col}" missing in one stage',
            expected='column present in both', actual='column missing',
        )
    upstream_ids   = set(upstream_df[join_col].dropna())
    downstream_ids = set(downstream_df[join_col].dropna())
    missing        = upstream_ids - downstream_ids
    pct_missing    = len(missing) / len(upstream_ids) if upstream_ids else 0

    if pct_missing > tolerance:
        return CheckResult(
            check_name='cross_stage_id_leakage', stage=stage_name, passed=False,
            severity='critical' if pct_missing > 0.15 else 'warning',
            message=f'{pct_missing:.1%} of order IDs from upstream missing downstream ({len(missing)} IDs)',
            expected=f'< {tolerance:.0%} missing', actual=f'{pct_missing:.1%} missing',
            details={'missing_count': len(missing), 'missing_pct': round(pct_missing, 4)},
        )
    return CheckResult(
        check_name='cross_stage_id_leakage', stage=stage_name, passed=True,
        severity='info',
        message=f'ID continuity OK: {pct_missing:.1%} missing across stages',
        expected=f'< {tolerance:.0%} missing', actual=f'{pct_missing:.1%} missing',
    )


# ──────────────────────────────────────────────
# Automatic column-level checks
# ──────────────────────────────────────────────

def run_column_checks(df, stage_name, baseline_df, thresholds=None):
    """
    Automatically classify every column and run appropriate checks.
    Returns a list of CheckResults — one (or two) per column. ID columns are skipped.
    """
    classification = classify_columns(df)
    results        = []

    for col, col_type in classification.items():
        if col_type == 'id':
            continue

        elif col_type == 'datetime':
            results.append(check_timestamp_freshness(df, stage_name, col, thresholds))

        elif col_type == 'numeric':
            results.append(check_null_rate(df, stage_name, col, thresholds=thresholds))
            if col in baseline_df.columns:
                base_numeric = pd.to_numeric(baseline_df[col], errors='coerce')
                if not base_numeric.isna().all():
                    expected_mean = float(base_numeric.mean())
                    results.append(check_value_distribution(df, stage_name, col, expected_mean, thresholds))

        elif col_type == 'categorical':
            results.append(check_categorical_health(df, stage_name, col, baseline_df, thresholds))

    return results


# ──────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────

def run_detection(stages: dict, baseline: dict, thresholds: dict = None) -> dict:
    """
    Run all checks across all pipeline stages.
    Returns dict of stage_name -> list[CheckResult].
    """
    t = thresholds or {}

    s1, s1_b = stages['1_ingest'],    baseline['1_ingest']
    s2, s2_b = stages['2_enrich'],    baseline['2_enrich']
    s3, s3_b = stages['3_transform'], baseline['3_transform']
    s4, s4_b = stages['4_aggregate'], baseline['4_aggregate']
    s5, s5_b = stages['5_output'],    baseline['5_output']

    return {
        '1_ingest': [
            check_row_count(s1, '1_ingest', len(s1_b), t),
            check_canary(s1, '1_ingest'),
            *run_column_checks(s1, '1_ingest', s1_b, t),
        ],
        '2_enrich': [
            check_row_count(s2, '2_enrich', len(s2_b), t),
            check_canary(s2, '2_enrich'),
            check_cross_stage_leakage(s1, s2, '2_enrich', thresholds=t),
            *run_column_checks(s2, '2_enrich', s2_b, t),
        ],
        '3_transform': [
            check_row_count(s3, '3_transform', len(s3_b), t),
            check_canary(s3, '3_transform'),
            *run_column_checks(s3, '3_transform', s3_b, t),
        ],
        '4_aggregate': [
            check_row_count(s4, '4_aggregate', len(s4_b), t),
            check_canary(s4, '4_aggregate'),
            check_cross_stage_leakage(s3, s4, '4_aggregate', thresholds=t),
            *run_column_checks(s4, '4_aggregate', s4_b, t),
        ],
        '5_output': [
            check_row_count(s5, '5_output', len(s5_b), t),
            *run_column_checks(s5, '5_output', s5_b, t),
        ],
    }


def summarise_results(results: dict) -> dict:
    all_checks = [c for checks in results.values() for c in checks]
    total      = len(all_checks)
    passed     = sum(1 for c in all_checks if c.passed)
    criticals  = sum(1 for c in all_checks if not c.passed and c.severity == 'critical')
    warnings   = sum(1 for c in all_checks if not c.passed and c.severity == 'warning')

    stage_health = {}
    for stage, checks in results.items():
        n = len(checks)
        p = sum(1 for c in checks if c.passed)
        stage_health[stage] = {
            'passed': p, 'total': n,
            'health_pct': round(100 * p / n, 1) if n else 0
        }

    return {
        'total_checks':   total,
        'passed':         passed,
        'failed':         total - passed,
        'criticals':      criticals,
        'warnings':       warnings,
        'overall_health': round(100 * passed / total, 1) if total else 0,
        'stage_health':   stage_health,
    }


def build_column_health_matrix(results: dict) -> pd.DataFrame:
    """
    Build a (columns × stages) DataFrame for the column-level heatmap.

    Score per cell:
      1.0  = all checks on this column passed at this stage  (green)
      0.5  = at least one warning                            (orange)
      0.0  = at least one critical                           (red)
      NaN  = column not present / not checked at this stage  (grey)
    """
    TABLE_LEVEL = {
        'row_count', 'row_count_drop', 'row_count_spike',
        'canary_record', 'cross_stage_id_leakage'
    }

    records = []
    for stage, checks in results.items():
        for c in checks:
            if c.check_name in TABLE_LEVEL or c.column is None:
                continue
            score = 1.0 if c.passed else (0.5 if c.severity == 'warning' else 0.0)
            records.append({'column': c.column, 'stage': stage, 'score': score})

    if not records:
        return pd.DataFrame()

    df     = pd.DataFrame(records)
    df     = df.groupby(['column', 'stage'])['score'].min().reset_index()
    matrix = df.pivot(index='column', columns='stage', values='score')

    stage_order = ['1_ingest', '2_enrich', '3_transform', '4_aggregate', '5_output']
    matrix      = matrix.reindex(columns=[s for s in stage_order if s in matrix.columns])

    return matrix
