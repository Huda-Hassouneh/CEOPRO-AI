"""
Currency-aware rounding/formatting. Prices were rounded to 2 decimals
everywhere, but ISO 4217 currencies differ: the Jordanian dinar (the
platform's default), Kuwaiti/Bahraini dinar, Omani rial, Tunisian/Libyan
dinar and Iraqi dinar have 3 minor-unit digits (1 JOD = 1000 fils), and the
yen, won, dong, CFA francs etc. have none. Rounding 1.125 JOD to 1.13 - or
showing 1500 XOF as 1500.00 - is wrong for those businesses.
"""
from typing import Optional

_THREE_DECIMALS = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}
_ZERO_DECIMALS = {
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF",
    "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
}


def minor_units(currency: Optional[str]) -> int:
    code = (currency or "").strip().upper()
    if code in _THREE_DECIMALS:
        return 3
    if code in _ZERO_DECIMALS:
        return 0
    return 2


def round_money(amount: float, currency: Optional[str]) -> float:
    return round(float(amount), minor_units(currency))


def format_money(amount: float, currency: Optional[str]) -> str:
    """'12.500' for JOD, '1500' for XOF, '9.99' for USD - no currency code."""
    return f"{float(amount):.{minor_units(currency)}f}"


def format_money_text(amount: float, currency: Optional[str]) -> str:
    """Rounded like format_money but without trailing zeros: '25' and
    '12.5' rather than '25.000' and '12.500' for JOD. For text a language
    model reads - in many countries '25.000' means twenty-five thousand,
    and a live assistant run read a 25 JOD price exactly that way."""
    text = format_money(amount, currency)
    return text.rstrip("0").rstrip(".") if "." in text else text
