import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

RANDOM_SEED = 42

def generate_olist_data(n_orders=500, seed=RANDOM_SEED):
    rng = np.random.default_rng(seed)
    random.seed(seed)

    # --- Customers ---
    states = ['SP', 'RJ', 'MG', 'RS', 'PR', 'SC', 'BA', 'GO', 'ES', 'PE']
    n_customers = int(n_orders * 1.1)
    customers = pd.DataFrame({
        'customer_id': [f'CUST_{i:05d}' for i in range(n_customers)],
        'customer_city': rng.choice(['sao paulo', 'rio de janeiro', 'belo horizonte', 'curitiba', 'porto alegre'], n_customers),
        'customer_state': rng.choice(states, n_customers),
    })

    # --- Sellers ---
    n_sellers = 50
    sellers = pd.DataFrame({
        'seller_id': [f'SELL_{i:04d}' for i in range(n_sellers)],
        'seller_city': rng.choice(['sao paulo', 'rio de janeiro', 'curitiba'], n_sellers),
        'seller_state': rng.choice(states[:5], n_sellers),
    })

    # --- Products ---
    categories = ['electronics', 'furniture', 'toys', 'fashion', 'sports', 'books', 'beauty', 'food']
    n_products = 100
    products = pd.DataFrame({
        'product_id': [f'PROD_{i:05d}' for i in range(n_products)],
        'product_category': rng.choice(categories, n_products),
        'product_weight_g': rng.integers(100, 15000, n_products),
        'product_length_cm': rng.integers(10, 100, n_products),
    })

    # --- Orders ---
    purchase_dates = [datetime(2023, 1, 1) + timedelta(days=int(d)) for d in rng.integers(0, 365, n_orders)]
    approved_offsets = rng.integers(0, 2, n_orders)
    delivery_offsets = rng.integers(5, 30, n_orders)
    estimated_offsets = rng.integers(15, 40, n_orders)

    orders = pd.DataFrame({
        'order_id': [f'ORD_{i:06d}' for i in range(n_orders)],
        'customer_id': rng.choice(customers['customer_id'], n_orders),
        'order_status': rng.choice(['delivered', 'shipped', 'canceled', 'processing'], n_orders, p=[0.75, 0.12, 0.08, 0.05]),
        'order_purchase_timestamp': purchase_dates,
        'order_approved_at': [purchase_dates[i] + timedelta(days=int(approved_offsets[i])) for i in range(n_orders)],
        'order_delivered_timestamp': [purchase_dates[i] + timedelta(days=int(delivery_offsets[i])) for i in range(n_orders)],
        'order_estimated_delivery': [purchase_dates[i] + timedelta(days=int(estimated_offsets[i])) for i in range(n_orders)],
    })

    # --- Order Items ---
    items = pd.DataFrame({
        'order_id': rng.choice(orders['order_id'], n_orders),
        'product_id': rng.choice(products['product_id'], n_orders),
        'seller_id': rng.choice(sellers['seller_id'], n_orders),
        'price': rng.uniform(20, 500, n_orders).round(2),
        'freight_value': rng.uniform(5, 80, n_orders).round(2),
    })

    # --- Payments ---
    payments = pd.DataFrame({
        'order_id': orders['order_id'],
        'payment_type': rng.choice(['credit_card', 'boleto', 'voucher', 'debit_card'], n_orders, p=[0.74, 0.19, 0.05, 0.02]),
        'payment_installments': rng.integers(1, 12, n_orders),
        'payment_value': (items.groupby('order_id')['price'].sum().reindex(orders['order_id']).values + rng.uniform(5, 80, n_orders)).round(2),
    })

    # --- Reviews ---
    reviews = pd.DataFrame({
        'order_id': orders['order_id'],
        'review_score': rng.integers(1, 6, n_orders),
        'review_creation_date': [purchase_dates[i] + timedelta(days=int(d)) for i, d in enumerate(rng.integers(10, 45, n_orders))],
    })

    # Add canary rows - known synthetic records we can track end-to-end
    canary_order_id = 'ORD_CANARY_001'
    canary_customer_id = 'CUST_CANARY_001'
    canary_seller_id = 'SELL_CANARY_001'
    canary_product_id = 'PROD_CANARY_001'

    canary_purchase = datetime(2023, 6, 15)
    canary_order = pd.DataFrame([{
        'order_id': canary_order_id,
        'customer_id': canary_customer_id,
        'order_status': 'delivered',
        'order_purchase_timestamp': canary_purchase,
        'order_approved_at': canary_purchase + timedelta(days=1),
        'order_delivered_timestamp': canary_purchase + timedelta(days=10),
        'order_estimated_delivery': canary_purchase + timedelta(days=15),
    }])
    canary_customer = pd.DataFrame([{'customer_id': canary_customer_id, 'customer_city': 'canary city', 'customer_state': 'SP'}])
    canary_item = pd.DataFrame([{'order_id': canary_order_id, 'product_id': canary_product_id, 'seller_id': canary_seller_id, 'price': 999.99, 'freight_value': 10.00}])
    canary_payment = pd.DataFrame([{'order_id': canary_order_id, 'payment_type': 'credit_card', 'payment_installments': 1, 'payment_value': 1009.99}])
    canary_review = pd.DataFrame([{'order_id': canary_order_id, 'review_score': 5, 'review_creation_date': canary_purchase + timedelta(days=12)}])
    canary_seller = pd.DataFrame([{'seller_id': canary_seller_id, 'seller_city': 'canary city', 'seller_state': 'SP'}])
    canary_product = pd.DataFrame([{'product_id': canary_product_id, 'product_category': 'canary', 'product_weight_g': 100, 'product_length_cm': 10}])

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