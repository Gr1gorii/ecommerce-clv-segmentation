import numpy as np


ACTIONS = {
    "Active high-value": "Personal offers and early access without blanket discounts",
    "High-value dormant": "Reactivation test with a control group",
    "Regular": "Product recommendations and easy repeat ordering",
    "New": "Onboarding after the first purchase",
    "One purchase": "Low-cost email sequence for a second order",
    "Dormant": "Occasional emails without an expensive personal campaign",
}


def add_segments(customers):
    customers = customers.copy()
    customers["r_score"] = 6 - np.ceil(customers["days_since_purchase"].rank(pct=True, method="max") * 5).astype(int)
    customers["f_score"] = np.ceil(customers["purchases"].rank(pct=True, method="max") * 5).astype(int)
    customers["m_score"] = np.ceil(customers["revenue"].rank(pct=True, method="max") * 5).astype(int)
    customers["rfm"] = customers[["r_score", "f_score", "m_score"]].astype(str).agg("".join, axis=1)
    threshold = customers["discounted_revenue"].quantile(0.75)
    single = customers["purchases"].eq(1)
    new = single & customers["T"].le(90)
    sleeping = customers["days_since_purchase"].gt(90)
    valuable = customers["discounted_revenue"].ge(threshold)
    customers["segment"] = np.select(
        [new, single, sleeping & valuable, sleeping, valuable],
        ["New", "One purchase", "High-value dormant", "Dormant", "Active high-value"],
        default="Regular",
    )
    customers["action"] = customers["segment"].map(ACTIONS)
    return customers, float(threshold)


def apply_economics(customers, margin=0.35, returns=0.05, reserve=0.50, service_cost=2.0):
    if not all(0 <= value <= 1 for value in [margin, returns, reserve]) or service_cost < 0:
        raise ValueError("Shares must be between 0 and 1; costs cannot be negative")
    customers = customers.copy()
    customers["contribution_clv"] = (customers["discounted_revenue"] * (1 - returns) * margin - service_cost).clip(lower=0)
    customers["cac_reference"] = customers["contribution_clv"] * reserve
    return customers


def apply_cac_range(customers, bias_low, bias_high, margin=0.35, returns=0.05, reserve=0.50, service_cost=2.0):
    if not np.isfinite([bias_low, bias_high]).all() or not -1 < bias_low <= bias_high:
        raise ValueError("Bias bounds must be finite, ordered and greater than -1")
    customers = apply_economics(customers, margin, returns, reserve, service_cost)
    for column, bias in [("cac_lower", bias_high), ("cac_upper", bias_low)]:
        scenario = customers.copy()
        scenario["discounted_revenue"] = customers["discounted_revenue"] / (1 + bias)
        customers[column] = apply_economics(scenario, margin, returns, reserve, service_cost)["cac_reference"]
    return customers


def campaign_scenario(customers, uplift=0.02, contact_cost=1.0, discount=0.0, margin=0.35, returns=0.05):
    if not 0 <= uplift <= 1 or not 0 <= discount <= margin or contact_cost < 0:
        raise ValueError("Check uplift, contact cost and discount")
    incremental = uplift * customers["expected_basket"] * (1 - returns) * (margin - discount)
    return incremental.sum() - len(customers) * contact_cost
