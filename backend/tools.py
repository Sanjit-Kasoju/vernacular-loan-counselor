"""
tools.py  –  Deterministic loan eligibility & EMI calculator
Based on HomeFirst Finance parameters (Indian home loan norms)
"""

import json


# ─── HomeFirst / Industry Standard Parameters ───────────────────────────────
MAX_LTV = {          # Loan-to-Value caps (RBI guidelines)
    "<=30L": 0.90,   # up to ₹30 lakh → 90 % LTV
    "30L-75L": 0.80, # ₹30L – ₹75L  → 80 % LTV
    ">75L": 0.75,    # above ₹75L    → 75 % LTV
}
MAX_FOIR = 0.50      # Fixed Obligation-to-Income Ratio cap (50 %)
MIN_INCOME = 15_000  # Minimum net monthly income (₹)
MAX_TENURE_YEARS = 30
INTEREST_RATE_PA = 0.0875   # 8.75 % p.a. (HomeFirst typical rate)


def calculate_emi(principal: float, tenure_years: int,
                  annual_rate: float = INTEREST_RATE_PA) -> dict:
    """
    Calculate monthly EMI using standard reducing-balance formula.

    Args:
        principal      : Loan amount in ₹
        tenure_years   : Loan duration in years (1–30)
        annual_rate    : Annual interest rate as decimal (default 8.75 %)

    Returns:
        dict with emi, total_amount, total_interest
    """
    tenure_years = min(max(int(tenure_years), 1), MAX_TENURE_YEARS)
    n = tenure_years * 12                  # total months
    r = annual_rate / 12                   # monthly rate

    if r == 0:
        emi = principal / n
    else:
        emi = principal * r * (1 + r) ** n / ((1 + r) ** n - 1)

    total_amount  = emi * n
    total_interest = total_amount - principal

    return {
        "emi": round(emi, 2),
        "total_amount": round(total_amount, 2),
        "total_interest": round(total_interest, 2),
        "tenure_months": n,
        "annual_rate_pct": round(annual_rate * 100, 2),
    }


def check_eligibility(monthly_income: float,
                      property_value: float,
                      loan_amount_requested: float,
                      employment_status: str,
                      existing_emi: float = 0.0) -> dict:
    """
    Evaluate home loan eligibility using HomeFirst-style rule engine.

    Args:
        monthly_income          : Net monthly income in ₹
        property_value          : Property value in ₹
        loan_amount_requested   : Requested loan in ₹
        employment_status       : 'salaried' | 'self_employed' | 'business'
        existing_emi            : Existing monthly EMI obligations in ₹

    Returns:
        dict with eligible (bool), approved_amount, reason, lead_score
    """
    reasons = []
    approved_amount = loan_amount_requested

    # ── 1. Minimum income check ──────────────────────────────────────────────
    if monthly_income < MIN_INCOME:
        return {
            "eligible": False,
            "approved_amount": 0,
            "reason": f"Monthly income ₹{monthly_income:,.0f} is below the minimum threshold of ₹{MIN_INCOME:,.0f}.",
            "lead_score": "LOW",
        }

    # ── 2. Employment status check ───────────────────────────────────────────
    if employment_status.lower() not in ("salaried", "self_employed", "business"):
        reasons.append("Employment status unclear – additional documents may be needed.")

    # ── 3. LTV cap ───────────────────────────────────────────────────────────
    if property_value <= 30_00_000:
        ltv_cap = MAX_LTV["<=30L"]
    elif property_value <= 75_00_000:
        ltv_cap = MAX_LTV["30L-75L"]
    else:
        ltv_cap = MAX_LTV[">75L"]

    max_by_ltv = property_value * ltv_cap

    if loan_amount_requested > max_by_ltv:
        approved_amount = max_by_ltv
        reasons.append(
            f"Loan reduced to ₹{approved_amount:,.0f} to comply with LTV cap ({ltv_cap*100:.0f}% of property value)."
        )

    # ── 4. FOIR check ────────────────────────────────────────────────────────
    proposed_emi_info = calculate_emi(approved_amount, 20)
    proposed_emi      = proposed_emi_info["emi"]
    total_obligations = proposed_emi + existing_emi
    foir              = total_obligations / monthly_income

    if foir > MAX_FOIR:
        # Recalculate max affordable loan
        max_emi = (MAX_FOIR * monthly_income) - existing_emi
        if max_emi <= 0:
            return {
                "eligible": False,
                "approved_amount": 0,
                "reason": "Existing obligations already exceed FOIR limit.",
                "lead_score": "LOW",
            }
        # Back-calculate principal from max EMI
        r = INTEREST_RATE_PA / 12
        n = 20 * 12
        max_principal = max_emi * ((1 + r) ** n - 1) / (r * (1 + r) ** n)
        approved_amount = min(approved_amount, max_principal)
        reasons.append(
            f"Loan adjusted to ₹{approved_amount:,.0f} to keep FOIR within {MAX_FOIR*100:.0f}%."
        )

    # ── 5. Final EMI on approved amount ─────────────────────────────────────
    final_emi_info = calculate_emi(approved_amount, 20)

    # ── 6. Lead scoring ──────────────────────────────────────────────────────
    if approved_amount >= loan_amount_requested * 0.9:
        lead_score = "HIGH"
    elif approved_amount >= loan_amount_requested * 0.6:
        lead_score = "MEDIUM"
    else:
        lead_score = "LOW"

    summary = f"Eligible for ₹{approved_amount:,.0f} at EMI of ₹{final_emi_info['emi']:,.0f}/month for 20 years."
    if reasons:
        summary += " Note: " + " | ".join(reasons)

    return {
        "eligible": True,
        "approved_amount": round(approved_amount, 2),
        "emi": final_emi_info["emi"],
        "reason": summary,
        "lead_score": lead_score,
        "foir_pct": round(foir * 100, 1),
    }


# ── Gemini function-calling schema ──────────────────────────────────────────
TOOL_DECLARATIONS = [
    {
        "name": "calculate_emi",
        "description": (
            "Calculate the monthly EMI for a home loan. "
            "Call this when the user asks 'how much will I pay per month?' or wants to know the EMI."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "principal":     {"type": "number",  "description": "Loan amount in INR"},
                "tenure_years":  {"type": "integer", "description": "Loan tenure in years (1–30)"},
                "annual_rate":   {"type": "number",  "description": "Annual interest rate as decimal, default 0.0875"},
            },
            "required": ["principal", "tenure_years"],
        },
    },
    {
        "name": "check_eligibility",
        "description": (
            "Check home loan eligibility using deterministic rules. "
            "Call this ONLY when you have collected: monthly_income, property_value, "
            "loan_amount_requested, and employment_status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "monthly_income":         {"type": "number", "description": "Net monthly income in INR"},
                "property_value":         {"type": "number", "description": "Property value in INR"},
                "loan_amount_requested":  {"type": "number", "description": "Requested loan amount in INR"},
                "employment_status":      {"type": "string", "description": "'salaried', 'self_employed', or 'business'"},
                "existing_emi":           {"type": "number", "description": "Existing monthly EMI obligations in INR (default 0)"},
            },
            "required": ["monthly_income", "property_value", "loan_amount_requested", "employment_status"],
        },
    },
]


def dispatch_tool(name: str, args: dict) -> str:
    """Route a Gemini function-call to the correct Python function."""
    if name == "calculate_emi":
        result = calculate_emi(**args)
    elif name == "check_eligibility":
        result = check_eligibility(**args)
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result)
