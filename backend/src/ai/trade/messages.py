"""
The landed-cost calculation's wording in Arabic.

landed_cost.py writes its labels, formulas, missing-input explanations and
assumptions in English; localize() returns the same result with that
wording in the user's language. Figures, keys and units are never touched.
"""
import re
from typing import Dict, List, Tuple

_AR_EXACT: Dict[str, str] = {
    # step labels
    "Goods value": "قيمة البضاعة", "Freight": "الشحن", "Insurance": "التأمين", "Customs duty": "الرسوم الجمركية",
    "Specific duty": "الرسم النوعي", "Excise tax": "الضريبة الانتقائية", "Sales tax / VAT base": "وعاء ضريبة المبيعات / القيمة المضافة",
    "Import sales tax / VAT": "ضريبة المبيعات / القيمة المضافة على الاستيراد", "Landed cost (total)": "التكلفة الواصلة (الإجمالي)",
    "Landed cost per unit": "التكلفة الواصلة للوحدة",
    "Landed cost per unit before recoverable VAT": "التكلفة الواصلة للوحدة قبل الضريبة القابلة للاسترداد",
    "Saving versus local purchase (total)": "التوفير مقارنة بالشراء المحلي (الإجمالي)",
    "Margin per unit at your selling price": "هامش الربح للوحدة بسعر البيع لديك", "Margin": "هامش الربح",
    "Brokerage": "أجور الوساطة", "Clearance": "التخليص الجمركي", "Port handling": "مناولة الميناء", "Inspection": "الفحص",
    "Testing": "الاختبارات", "Certification": "شهادات المطابقة", "Permits": "التصاريح", "Documentation": "المستندات",
    "Bank fees": "الرسوم البنكية", "Warehousing": "التخزين", "Local delivery": "التوصيل المحلي", "Other": "تكاليف أخرى",
    # input names
    "Supplier unit price": "سعر المورد للوحدة", "Quantity": "الكمية", "Fx rate": "سعر الصرف",
    "Duty rate": "نسبة الرسوم الجمركية", "Specific duty per unit": "الرسم النوعي للوحدة",
    "Excise rate": "نسبة الضريبة الانتقائية", "Sales tax rate": "نسبة ضريبة المبيعات", "Local unit price": "السعر المحلي للوحدة",
    "Selling price": "سعر البيع",
    # formulas
    "unit price × quantity": "سعر الوحدة × الكمية", "goods value × exchange rate": "قيمة البضاعة × سعر الصرف",
    "freight for the shipment": "شحن الإرسالية", "insurance for the shipment": "تأمين الإرسالية",
    "goods + freight + insurance": "البضاعة + الشحن + التأمين", "goods value": "قيمة البضاعة",
    "customs value × duty rate": "القيمة الجمركية × نسبة الرسوم", "duty per unit × quantity": "الرسم للوحدة × الكمية",
    "(customs value + duty) × excise rate": "(القيمة الجمركية + الرسوم) × نسبة الضريبة الانتقائية",
    "customs value + duty + excise": "القيمة الجمركية + الرسوم + الضريبة الانتقائية", "customs value": "القيمة الجمركية",
    "tax base × tax rate": "وعاء الضريبة × نسبة الضريبة", "as stated": "كما ذُكر",
    "goods + freight + insurance + duty + excise + tax + other costs":
        "البضاعة + الشحن + التأمين + الرسوم + الضريبة الانتقائية + الضريبة + التكاليف الأخرى",
    "landed cost ÷ quantity": "التكلفة الواصلة ÷ الكمية",
    "(landed cost − import VAT) ÷ quantity": "(التكلفة الواصلة − ضريبة الاستيراد) ÷ الكمية",
    "local price × quantity − landed cost": "السعر المحلي × الكمية − التكلفة الواصلة",
    "selling price − landed cost per unit": "سعر البيع − التكلفة الواصلة للوحدة",
    "margin per unit ÷ selling price × 100": "هامش الوحدة ÷ سعر البيع × 100",
    # missing inputs
    "the supplier's price per unit (a written quotation is best)": "سعر المورد للوحدة (يفضّل عرض سعر مكتوب)",
    "how many units the order is for": "عدد الوحدات في الطلبية",
    "the order quantity must be more than zero": "يجب أن تكون كمية الطلبية أكثر من صفر",
    "the freight cost for this shipment (a forwarder's quotation)": "تكلفة شحن هذه الإرسالية (عرض سعر من شركة الشحن)",
    "the cargo insurance cost (often a small % of the goods value)": "تكلفة تأمين البضاعة (غالباً نسبة صغيرة من قيمتها)",
    "the customs duty rate for the product's HS code, origin and destination":
        "نسبة الرسوم الجمركية حسب البند الجمركي للمنتج وبلد المنشأ وبلد الوصول",
    "the import sales tax / VAT rate for this product in the destination":
        "نسبة ضريبة المبيعات / القيمة المضافة على استيراد هذا المنتج في بلد الوصول",
    # assumptions and exclusions
    "No delivery term (Incoterm) was given: the supplier price is treated as covering the goods only (like EXW/FOB), "
    "so freight and insurance are added.":
        "لم يُذكر شرط تسليم (Incoterm)، لذلك اعتُبر سعر المورد للبضاعة فقط (مثل EXW/FOB) وأضيف الشحن والتأمين.",
    "Customs value is taken on a CIF basis (goods + freight + insurance), the basis most Arab and WTO customs "
    "administrations use; confirm it for the destination.":
        "احتُسبت القيمة الجمركية على أساس CIF (البضاعة + الشحن + التأمين)، وهو الأساس المعتمد لدى معظم الإدارات "
        "الجمركية العربية ووفق منظمة التجارة العالمية؛ تأكّد منه لبلد الوصول.",
    "Sales tax / VAT is charged on the customs value plus duty and excise, the usual import base; confirm it for the "
    "destination.":
        "تُحتسب ضريبة المبيعات / القيمة المضافة على القيمة الجمركية مضافاً إليها الرسوم والضريبة الانتقائية، وهو "
        "الوعاء المعتاد عند الاستيراد؛ تأكّد منه لبلد الوصول.",
    "If the business is VAT/sales-tax registered and can reclaim import VAT, the per-unit cost before recoverable VAT "
    "is the relevant one.":
        "إذا كانت المنشأة مسجّلة في ضريبة المبيعات / القيمة المضافة وتستطيع استرداد ضريبة الاستيراد، فالتكلفة "
        "للوحدة قبل الضريبة القابلة للاسترداد هي الأدق.",
    "Clearance, brokerage, inspection, certification, permits, port handling, storage and local delivery were not "
    "provided, so they are not included.":
        "لم تُذكر تكاليف التخليص والوساطة والفحص والشهادات والتصاريح ومناولة الميناء والتخزين والتوصيل المحلي، "
        "لذلك هي غير مشمولة.",
    "counts clearance, brokerage, inspection, certification, permits, documentation and bank fees as fixed per "
    "shipment; freight, insurance, duty and tax as changing with the quantity":
        "تُعدّ رسوم التخليص والوساطة والفحص والشهادات والتصاريح والمستندات والرسوم البنكية ثابتة لكل إرسالية، "
        "والشحن والتأمين والرسوم والضريبة متغيرة مع الكمية",
    "importing costs more per unit than buying locally before any fixed costs, so no order size makes it cheaper at "
    "these rates":
        "تكلفة الاستيراد للوحدة أعلى من الشراء المحلي حتى قبل التكاليف الثابتة، لذلك لا توجد كمية تجعله أرخص بهذه الأسعار",
    # sensitivity scenarios
    "Exchange rate 5% less favourable": "سعر صرف أسوأ بنسبة 5%", "Exchange rate 5% more favourable": "سعر صرف أفضل بنسبة 5%",
    "Freight 25% higher": "شحن أعلى بنسبة 25%", "Freight 25% lower": "شحن أقل بنسبة 25%",
    "Half the quantity": "نصف الكمية", "Double the quantity": "ضعف الكمية",
}
_AR_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^Goods value in (\w+)$"), r"قيمة البضاعة بـ \1"),
    (re.compile(r"^Customs value \((\w+) basis\)$"), r"القيمة الجمركية (على أساس \1)"),
    (re.compile(r"^the exchange rate from (\w+) to (\w+) on the payment date$"), r"سعر صرف \1 مقابل \2 في تاريخ الدفع"),
    (re.compile(r"^(.+) is included in the supplier's price under (\w+)\.$"), r"\1 مشمول في سعر المورد وفق شرط \2."),
    (re.compile(r"^Import duty is paid by the seller under (\w+)\.$"), r"الرسوم الجمركية يدفعها البائع وفق شرط \1."),
    (re.compile(r"^Import sales tax / VAT is paid by the seller under (\w+)\.$"),
     r"ضريبة الاستيراد يدفعها البائع وفق شرط \1."),
]


def translate(text: str, language: str) -> str:
    if language != "ar" or not text:
        return text
    if text in _AR_EXACT:
        return _AR_EXACT[text]
    for pattern, replacement in _AR_PATTERNS:
        if pattern.match(text):
            translated = pattern.sub(replacement, text)
            return re.sub(r"^(Freight|Insurance)", lambda m: _AR_EXACT.get(m.group(1), m.group(1)), translated)
    return text


def localize(result: dict, language: str) -> dict:
    """A landed_cost.Result.as_dict() with its wording in `language`."""
    if language != "ar":
        return result
    out = dict(result)
    out["steps"] = [{**step, "label": translate(step["label"], language), "formula": translate(step["formula"], language)}
                    for step in result.get("steps") or []]
    out["missing"] = [{**item, "why": translate(item["why"], language)} for item in result.get("missing") or []]
    out["assumptions"] = [translate(text, language) for text in result.get("assumptions") or []]
    out["exclusions"] = [translate(text, language) for text in result.get("exclusions") or []]
    if result.get("comparison"):
        comparison = dict(result["comparison"])
        if comparison.get("break_even_note"):
            comparison["break_even_note"] = translate(comparison["break_even_note"], language)
        out["comparison"] = comparison
    out["sensitivity"] = [{**row, "label": translate(row["label"], language)} for row in result.get("sensitivity") or []]
    return out
