# Detection Thresholds

This document describes all default thresholds used by `detection_engine.py`.
These values are defined in the `DEFAULT_THRESHOLDS` and `COLUMN_NULL_OVERRIDES`
dictionaries in that file. To change a threshold, edit those dictionaries directly.

> **Note:** This is a reference document. The system does not read from this file at runtime.

---

## Table-Level Thresholds (`DEFAULT_THRESHOLDS`)

These apply across the pipeline regardless of which column is being checked.

| Threshold | Default | Meaning |
|---|---|---|
| `row_drop_threshold` | `0.10` (10%) | Flag if row count falls more than 10% vs baseline. Warning between 10–20%, critical above 20%. |
| `row_spike_threshold` | `0.20` (20%) | Flag if row count rises more than 20% vs baseline. Suggests duplicate injection. Raises warning. |
| `null_rate_threshold` | `0.10` (10%) | Default max acceptable null rate for any column not listed in the overrides below. |
| `mean_drift_tolerance` | `0.30` (30%) | How much a numeric column's mean can shift from baseline before flagging. Raises warning. Negative values raise critical regardless of drift amount. |
| `leakage_tolerance` | `0.05` (5%) | Max fraction of order IDs allowed to go missing between consecutive stages. Above 5% raises warning, above 15% raises critical. |
| `stale_year_threshold` | `2018` | Timestamps with a max year below this are flagged as potentially stale. All identical timestamps across all rows raise critical. Set to 2018 to match the Olist dataset date range. |

---

## Per-Column Null Rate Overrides (`COLUMN_NULL_OVERRIDES`)

These override the default `null_rate_threshold` for specific columns that have legitimate
higher null rates in the real Olist data.

### Orders — legitimate nulls from order status

| Column | Override | Reason |
|---|---|---|
| `order_approved_at` | `0.01` (1%) | ~160 nulls in 99k rows — orders that were never formally approved |
| `order_delivered_carrier_date` | `0.03` (3%) | ~1,783 nulls — orders not yet picked up by carrier |
| `order_delivered_customer_date` | `0.04` (4%) | ~2,965 nulls — orders not yet delivered to customer |

### Computed columns — depend on delivery timestamps being present

| Column | Override | Reason |
|---|---|---|
| `delivery_days` | `0.05` (5%) | Null when delivery timestamps are missing |
| `is_late` | `0.05` (5%) | Null when delivery_days is null |
| `total_order_value` | `0.05` (5%) | Null when price or freight_value is missing |

### Review columns — not every order gets a review or comment

| Column | Override | Reason |
|---|---|---|
| `review_score` | `0.02` (2%) | Small fraction of orders have no review at all |
| `review_creation_date` | `0.02` (2%) | Same as review_score |
| `review_answer_timestamp` | `0.02` (2%) | Same as review_score |
| `review_comment_title` | `0.70` (70%) | Most customers leave a star rating but no written title |
| `review_comment_message` | `0.50` (50%) | Many customers leave no written message |

### Seller aggregate columns — depend on data being present for each seller

| Column | Override | Reason |
|---|---|---|
| `avg_review_score` | `0.10` (10%) | Sellers with no reviewed orders produce null |
| `late_delivery_rate` | `0.10` (10%) | Sellers with no delivered orders produce null |
| `avg_delivery_days` | `0.10` (10%) | Same as late_delivery_rate |

### Product columns — some products have missing dimension data

| Column | Override | Reason |
|---|---|---|
| `product_category_name` | `0.01` (1%) | Small number of uncategorised products |
| `product_name_lenght` | `0.01` (1%) | Missing for some products (note: typo is in original Olist dataset) |
| `product_description_lenght` | `0.01` (1%) | Same as above |
| `product_photos_qty` | `0.01` (1%) | Same as above |
| `product_weight_g` | `0.01` (1%) | Same as above |
| `product_length_cm` | `0.01` (1%) | Same as above |
| `product_height_cm` | `0.01` (1%) | Same as above |
| `product_width_cm` | `0.01` (1%) | Same as above |

---

## Severity Levels

| Level | Meaning |
|---|---|
| `info` | Check passed. No action needed. |
| `warning` | Something is suspicious. Investigate but may have an innocent explanation. |
| `critical` | Something is definitively wrong. Act immediately. |

---

## Column Classification

The detection engine automatically classifies every column and applies the appropriate checks.

| Type | Checks Applied |
|---|---|
| `id` | None — identifier columns are skipped entirely |
| `datetime` | Freshness check — looks for identical timestamps and stale years |
| `numeric` | Null rate check + distribution check (mean drift, negative values) |
| `categorical` | Null rate check + category drift check (new values not seen in baseline) |

Columns treated as IDs: `order_id`, `customer_id`, `seller_id`, `product_id`, `order_item_id`, `review_id`, `customer_unique_id`, `seller_zip_code_prefix`, `customer_zip_code_prefix`

Columns treated as datetimes: `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date`, `review_creation_date`, `review_answer_timestamp`, `shipping_limit_date`

---

## Notes for Version 2

When the rolling statistical baseline is implemented, the following thresholds
should become dynamic rather than hardcoded:

- `row_drop_threshold` and `row_spike_threshold` → derived from rolling std of row counts across historical runs
- `null_rate_threshold` → derived from rolling mean null rate per column
- `mean_drift_tolerance` → derived from rolling std of column means
- `stale_year_threshold` → replaced by a freshness window relative to the most recent run date
