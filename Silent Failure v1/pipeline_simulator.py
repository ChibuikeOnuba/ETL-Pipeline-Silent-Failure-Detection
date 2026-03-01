import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

def load_olist_data(data_dir='../data'):
    orders    = pd.read_csv(f'{data_dir}/olist_orders_dataset.csv')
    customers = pd.read_csv(f'{data_dir}/olist_customers_dataset.csv')
    sellers   = pd.read_csv(f'{data_dir}/olist_sellers_dataset.csv')
    products  = pd.read_csv(f'{data_dir}/olist_products_dataset.csv')
    items     = pd.read_csv(f'{data_dir}/olist_order_items_dataset.csv')
    payments  = pd.read_csv(f'{data_dir}/olist_order_payments_dataset.csv')
    reviews   = pd.read_csv(f'{data_dir}/olist_order_reviews_dataset.csv')
# Add canary rows - known synthetic records we can track end-to-end
    canary_order_id = 'ORD_CANARY_001'
    canary_customer_id = 'CUST_CANARY_001'
    canary_seller_id = 'SELL_CANARY_001'
    canary_product_id = 'PROD_CANARY_001'

    canary_purchase = datetime(2023, 6, 15)
    canary_order = pd.DataFrame([{
    'order_id': 'ORD_CANARY_001',
    'customer_id': 'CUST_CANARY_001',
    'order_status': 'delivered',
    'order_purchase_timestamp': '2017-01-01 00:00:00',
    'order_approved_at': '2017-01-02 00:00:00',
    'order_delivered_carrier_date': '2017-01-05 00:00:00',
    'order_delivered_customer_date': '2017-01-10 00:00:00',
    'order_estimated_delivery_date': '2017-01-15 00:00:00',
}])
    canary_customer = pd.DataFrame([{'customer_id': canary_customer_id, 'customer_city': 'canary city', 'customer_state': 'SP'}])
    canary_item = pd.DataFrame([{'order_id': canary_order_id, 'product_id': canary_product_id, 'seller_id': canary_seller_id, 'price': 999.99, 'freight_value': 10.00}])
    canary_payment = pd.DataFrame([{'order_id': canary_order_id, 'payment_type': 'credit_card', 'payment_installments': 1, 'payment_value': 1009.99}])
    canary_review = pd.DataFrame([{'order_id': canary_order_id, 'review_score': 5, 'review_creation_date': canary_purchase + timedelta(days=12)}])
    canary_seller = pd.DataFrame([{'seller_id': canary_seller_id, 'seller_city': 'canary city', 'seller_state': 'SP'}])
    canary_product = pd.DataFrame([{'product_id': canary_product_id, 'product_category_name': 'canary', 'product_weight_g': 100, 'product_length_cm': 10}])

    orders = pd.concat([orders, canary_order], ignore_index=True)
    customers = pd.concat([customers, canary_customer], ignore_index=True)
    items = pd.concat([items, canary_item], ignore_index=True)
    payments = pd.concat([payments, canary_payment], ignore_index=True)
    reviews = pd.concat([reviews, canary_review], ignore_index=True)
    sellers = pd.concat([sellers, canary_seller], ignore_index=True)
    products = pd.concat([products, canary_product], ignore_index=True)

    return {
        'orders': orders,
        'customers': customers,
        'sellers': sellers,
        'products': products,
        'items': items,
        'payments': payments,
        'reviews': reviews,
    }

# ──────────────────────────────────────────────
# FAILURE INJECTION
# Each function takes a dataframe and returns a (possibly broken) dataframe
# ──────────────────────────────────────────────

def inject_record_drop(df, drop_rate=0.20, seed=0):
    """Silently drop a fraction of rows. No error raised."""
    rng = np.random.default_rng(seed)
    mask = rng.random(len(df)) > drop_rate
    return df[mask].reset_index(drop=True)

def inject_stale_timestamps(df, col, stale_date=datetime(2022, 1, 1)):
    """Replace all timestamps with a stale fixed date."""
    df = df.copy()
    df[col] = stale_date
    return df

def inject_null_flood(df, col, null_rate=0.40, seed=1):
    """Flood a column with NaNs beyond normal null rate."""
    rng = np.random.default_rng(seed)
    df = df.copy()
    mask = rng.random(len(df)) < null_rate
    df.loc[mask, col] = np.nan
    return df

def inject_price_corruption(df, col='price', seed=2):
    """Set a chunk of prices to 0 or negative — passes schema checks but is semantically wrong."""
    rng = np.random.default_rng(seed)
    df = df.copy()
    mask = rng.random(len(df)) < 0.25
    df.loc[mask, col] = rng.choice([0, -1, -99.99], mask.sum())
    return df

def inject_duplicate_records(df, dup_rate=0.15, seed=3):
    """Silently duplicate rows — inflates counts."""
    rng = np.random.default_rng(seed)
    n_dups = int(len(df) * dup_rate)
    dup_idx = rng.integers(0, len(df), n_dups)
    dups = df.iloc[dup_idx]
    return pd.concat([df, dups], ignore_index=True)

def inject_schema_drift(df, col, new_type='str'):
    """Cast a numeric column to string — breaks downstream aggregations silently."""
    df = df.copy()
    df[col] = df[col].astype(new_type)
    return df

def inject_canary_removal(df, canary_col='order_id', canary_val='ORD_CANARY_001'):
    """Remove the canary row — simulates a filter that eats sentinel records."""
    return df[df[canary_col] != canary_val].reset_index(drop=True)


# ──────────────────────────────────────────────
# PIPELINE STAGES
# ──────────────────────────────────────────────

def stage_ingest(raw_data, failures):
    """Stage 1: Load and validate raw orders."""
    orders = raw_data['orders'].copy()

    if 'record_drop' in failures:
        orders = inject_record_drop(orders, drop_rate=failures['record_drop'])
    if 'stale_timestamps' in failures:
        orders = inject_stale_timestamps(orders, 'order_purchase_timestamp')
    if 'canary_removal' in failures:
        orders = inject_canary_removal(orders)

    return orders


def stage_enrich(orders, raw_data, failures):
    """Stage 2: Join customers, items, payments, reviews."""
    customers = raw_data['customers'].copy()
    items = raw_data['items'].copy()
    payments = raw_data['payments'].copy()

    if 'null_flood' in failures:
        customers = inject_null_flood(customers, 'customer_state', null_rate=failures['null_flood'])
    if 'duplicate_records' in failures:
        items = inject_duplicate_records(items, dup_rate=failures['duplicate_records'])
    if 'price_corruption' in failures:
        items = inject_price_corruption(items, 'price')

    enriched = orders.merge(customers, on='customer_id', how='left')
    enriched = enriched.merge(items, on='order_id', how='left')
    enriched = enriched.merge(payments, on='order_id', how='left')

    return enriched


def stage_transform(enriched, failures):
    """Stage 3: Calculate delivery metrics."""
    df = enriched.copy()

    if 'schema_drift' in failures:
        df = inject_schema_drift(df, 'price')

    # Try to compute delivery time — will silently produce NaT or errors if timestamps stale
    try:
        df['delivery_days'] = (
    pd.to_datetime(df['order_delivered_customer_date']) -
    pd.to_datetime(df['order_purchase_timestamp'])).dt.days

        df['is_late'] = (pd.to_datetime(df['order_delivered_customer_date']) > pd.to_datetime(df['order_estimated_delivery_date']))
        df['total_order_value'] = pd.to_numeric(df['price'], errors='coerce') + pd.to_numeric(df['freight_value'], errors='coerce')
    except Exception:
        df['delivery_days'] = np.nan
        df['is_late'] = np.nan
        df['total_order_value'] = np.nan

    return df


def stage_aggregate(transformed, raw_data, failures):
    """Stage 4: Compute seller-level performance KPIs."""
    sellers = raw_data['sellers'].copy()
    reviews = raw_data['reviews'].copy()

    df = transformed.merge(sellers, on='seller_id', how='left')
    df = df.merge(reviews, on='order_id', how='left')

    if 'record_drop' in failures and failures.get('agg_drop'):
        df = inject_record_drop(df, drop_rate=0.30, seed=99)

    agg = df.groupby('seller_id').agg(
        total_orders=('order_id', 'count'),
        total_revenue=('total_order_value', 'sum'),
        avg_delivery_days=('delivery_days', 'mean'),
        late_delivery_rate=('is_late', 'mean'),
        avg_review_score=('review_score', 'mean'),
    ).reset_index()

    return agg, df


def run_pipeline(raw_data, failures=None):
    """
    Run all pipeline stages and return outputs + metadata for detection.
    failures: dict of failure_name -> parameter
    """
    if failures is None:
        failures = {}

    stages = {}

    s1 = stage_ingest(raw_data, failures)
    stages['1_ingest'] = s1

    s2 = stage_enrich(s1, raw_data, failures)
    stages['2_enrich'] = s2

    s3 = stage_transform(s2, failures)
    stages['3_transform'] = s3

    s4_agg, s4_full = stage_aggregate(s3, raw_data, failures)
    stages['4_aggregate'] = s4_full
    stages['5_output'] = s4_agg

    return stages
