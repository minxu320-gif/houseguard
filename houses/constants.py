"""Domain constants (risk levels, pagination defaults)."""

# Risk levels (stored lowercase in DB)
RISK_LEVEL_LOW = "low"
RISK_LEVEL_MEDIUM = "medium"
RISK_LEVEL_HIGH = "high"
RISK_LEVEL_CRITICAL = "critical"

RISK_LEVEL_ORDER = (
    RISK_LEVEL_LOW,
    RISK_LEVEL_MEDIUM,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_CRITICAL,
)

DEFAULT_PAGE_SIZE = 12
RISK_ALERTS_PAGE_SIZE = 25
