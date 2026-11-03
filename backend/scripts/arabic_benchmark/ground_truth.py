"""
KEEL Arabic quality benchmark - ground truth (synthetic data only).

Every document, field, table cell, question and expected passage below is
synthetic ("Al-Nada Trading Demo" / "شركة الندى للتجارة"), written for this
benchmark. No customer data. Text is stored in Unicode LOGICAL order - the
order a correct extractor must return, whatever a viewer displays.

Documents are built from this file by build_corpus.py, so the ground truth
and the files can never drift apart.
"""

# --- Documents ---------------------------------------------------------------
# Each paragraph has a stable id: RAG gold passages and reading-order checks
# refer to them. "\f" in `pages` separates pages.

POLICY_AR = {
    "id": "policy_ar",
    "title": "سياسة الإرجاع والتوصيل – شركة الندى للتجارة",
    "lang": "ar",
    "pages": [
        [
            ("p1", "تلتزم شركة الندى للتجارة بتوصيل الطلبات داخل عمّان خلال ٤٨ ساعة من تأكيد الطلب، وخلال ٣ إلى ٥ أيام عمل لباقي المحافظات."),
            ("p2", "رسوم التوصيل داخل عمّان 2.50 دينار أردني، ويكون التوصيل مجانياً للطلبات التي تزيد قيمتها على 40 دينار."),
            ("p3", "يحق للعميل إرجاع المنتج خلال 14 يوماً من تاريخ الاستلام بشرط أن يكون في عبوته الأصلية وغير مستخدم."),
            ("p4", "لا تُقبل إعادة المنتجات الغذائية المفتوحة أو المنتجات المصنّفة تحت الرمز SKU-AN-1042 لأسباب صحية."),
            ("p5", "يُعاد المبلغ إلى وسيلة الدفع الأصلية خلال 7 أيام عمل، وتُخصم نسبة 5% رسوم معالجة من الطلبات المرتجعة بعد اليوم السابع."),
            ("p6", "للاستفسار يرجى زيارة https://alnada.example/returns أو الاتصال على الرقم 0791234567 من الأحد إلى الخميس."),
            ("p7", "تاريخ سريان هذه السياسة: 01/03/2026، وتحل محل السياسة السابقة الصادرة في 15/09/2025."),
            ("p8", "قال المدير العامّ: «إِنَّ رِضا العَميلِ هو غايتُنا الأولى»؛ لذلك نراجع هذه السياسة كل ستة أشهر."),
        ],
        [
            ("p9", "ساعات عمل خدمة العملاء من الساعة 9:00 صباحاً حتى 6:00 مساءً، ويمكن التواصل عبر البريد support@alnada.example."),
            ("p10", "في حال وصول المنتج تالفاً، يلتزم العميل بإبلاغنا خلال 24 ساعة مع إرفاق صورة واضحة للمنتج والفاتورة رقم INV-2026-0042."),
        ],
    ],
    "numbers": ["48", "3", "5", "2.50", "40", "14", "1042", "7", "5%", "0791234567", "01/03/2026", "15/09/2025",
                "9:00", "6:00", "24", "2026-0042"],
    "fields": {},
    "tables": [],
}

CONTRACT_AR = {
    "id": "contract_ar",
    "title": "عقد توريد زيت الزيتون",
    "lang": "ar",
    "pages": [[
        ("c1", "تم الاتفاق بين شركة الندى للتجارة (الطرف الأول) ومؤسسة الزيتونة الذهبية (الطرف الثاني) على توريد زيت الزيتون البكر الممتاز."),
        ("c2", "مدة العقد سنة واحدة تبدأ في 01/01/2026 وتنتهي في 31/12/2026."),
        ("c3", "يلتزم الطرف الثاني بتسليم الكميات خلال 10 أيام من تاريخ أمر الشراء."),
        ("TABLE", "price_table"),
        ("c4", "غرامة التأخير 1.5% من قيمة الشحنة عن كل يوم تأخير."),
        ("c5", "يتم الدفع خلال 30 يوماً من استلام الفاتورة بتحويل بنكي إلى الحساب JO71 CBJO 0010 0000 0000 0131 0003 02."),
    ]],
    "numbers": ["01/01/2026", "31/12/2026", "10", "1.5%", "30", "4.75", "120", "8.90", "80", "24.50"],
    "fields": {},
    "tables": [{
        "id": "price_table",
        "header": ["رمز المنتج", "اسم المنتج", "سعر الوحدة (دينار)", "الحد الأدنى للطلب"],
        "rows": [
            ["OL-500", "زيت زيتون بكر ممتاز 500 مل", "4.75", "120"],
            ["OL-1000", "زيت زيتون بكر ممتاز 1 لتر", "8.90", "80"],
            ["OL-3000", "زيت زيتون عبوة 3 لتر", "24.50", "30"],
        ],
    }],
}

PRICE_LIST_XLSX = {
    "id": "price_list_ar",
    "title": "قائمة الأسعار",
    "lang": "ar",
    "sheets": {
        "قائمة الأسعار": {
            "header": ["الرمز", "المنتج", "الفئة", "السعر", "الكمية المتوفرة"],
            # Cells given as str stay text in the workbook (Arabic-Indic digits typed by a user).
            "rows": [
                ["TH-01", "شاي أخضر 100 غرام", "مشروبات", 3.25, 140],
                ["CF-02", "قهوة عربية بالهيل 250 غرام", "مشروبات", "٦٫٥٠", "٧٥"],
                ["DT-03", "تمر مجدول 1 كغم", "تمور", 9.00, 60],
                ["HN-04", "عسل سدر 500 غرام", "عسل", 18.75, 22],
                ["OL-500", "زيت زيتون بكر ممتاز 500 مل", "زيوت", 4.75, 300],
            ],
        },
        "ملاحظات": {
            "header": ["ملاحظة"],
            "rows": [["الأسعار بالدينار الأردني وتشمل ضريبة المبيعات."]],
        },
    },
    # Values as a correct reader should normalise them (Arabic-Indic -> Western).
    "numbers": ["3.25", "140", "6.50", "75", "9", "60", "18.75", "22", "4.75", "300"],
}

MIXED_REPORT = {
    "id": "mixed_report_q1",
    "title": "التقرير الربعي Q1 2026 – Quarterly Report",
    "lang": "mixed",
    "pages": [
        [
            ("m1", "بلغت إجمالي المبيعات في الربع الأول 2026 مبلغ 128,450 دينار، بنمو 12.5% مقارنة بالربع نفسه من 2025."),
            ("m2", "Online sales via Shopify reached 41,200 JOD, which is 32% of total revenue."),
            ("m3", "كان المنتج الأكثر مبيعاً هو \"Zaytouna Extra Virgin Olive Oil 1L\" برمز OL-1000، بعدد 3,420 وحدة."),
            ("m4", "The average order value (AOV) increased from 18.40 JOD to 21.15 JOD."),
            ("m5", "انخفضت نسبة المرتجعات إلى 2.1% بعد تحديث سياسة الإرجاع في مارس."),
        ],
        [
            ("m6", "Top competitor: Al-Rayyan Market lowered its honey prices by 8% in February."),
            ("m7", "نوصي بزيادة مخزون عسل السدر HN-04 بنسبة 20% قبل شهر رمضان."),
            ("m8", "Marketing spend for the quarter was 6,300 JOD, mostly on Instagram and TikTok campaigns."),
        ],
        [
            ("m9", "ملخص: الأداء إيجابي، مع ضرورة مراقبة أسعار المنافسين في فئة العسل والتمور."),
        ],
    ],
    "numbers": ["2026", "128,450", "12.5%", "2025", "41,200", "32%", "1000", "3,420", "18.40", "21.15", "2.1%",
                "8%", "04", "20%", "6,300"],
    "fields": {},
    "tables": [],
}

# Two columns: in an RTL newsletter the RIGHT column is read first.
NEWSLETTER_2COL = {
    "id": "newsletter_2col_ar",
    "title": "نشرة الندى الإخبارية – شباط 2026",
    "lang": "ar",
    "columns": [
        [
            ("a1", "افتتحت شركة الندى فرعها الجديد في مدينة إربد بتاريخ 10 شباط 2026."),
            ("a2", "تبلغ مساحة الفرع الجديد 450 متراً مربعاً ويضم قسماً خاصاً للمنتجات المحلية."),
            ("a3", "يعمل في الفرع 18 موظفاً، ويستقبل العملاء يومياً من 8 صباحاً حتى 11 مساءً."),
        ],
        [
            ("b1", "أطلقنا برنامج الولاء \"نقاط الندى\" الذي يمنح العميل نقطة واحدة عن كل دينار."),
            ("b2", "يمكن استبدال كل 100 نقطة بقسيمة شراء قيمتها 5 دنانير."),
            ("b3", "انضم إلى البرنامج أكثر من 2,300 عميل خلال الشهر الأول."),
        ],
    ],
    "numbers": ["10", "2026", "450", "18", "8", "11", "100", "5", "2,300"],
    "fields": {},
    "tables": [],
}

HANDBOOK_EN = {
    "id": "handbook_en",
    "title": "Al-Nada Trading - Employee and Warehouse Handbook",
    "lang": "en",
    "pages": [[
        ("h1", "Warehouse stock counts are performed every Thursday at 4:00 PM."),
        ("h2", "Any inventory discrepancy above 3% must be reported to the operations manager within one business day."),
        ("h3", "Cold-chain products (dairy, fresh juice) must be stored between 2°C and 6°C."),
        ("h4", "The reorder point for olive oil 1L (OL-1000) is 150 units; the supplier lead time is 10 days."),
        ("h5", "Employees receive 21 days of annual leave after completing their first year."),
    ]],
    "numbers": ["4:00", "3%", "2", "6", "1000", "150", "10", "21"],
    "fields": {},
    "tables": [],
}

INVOICE_INDIC = {
    "id": "invoice_ar_indic",
    "title": "فاتورة مبيعات رقم ٢٠٢٦/٠٠٤٢",
    "lang": "ar",
    "pages": [[
        ("i1", "التاريخ: ١٥/٠٢/٢٠٢٦"),
        ("i2", "العميل: مطعم البيدر"),
        ("TABLE", "invoice_lines"),
        ("i3", "المجموع قبل الضريبة: ١٨٩٫٣٠ دينار"),
        ("i4", "ضريبة المبيعات ١٦٪: ٣٠٫٢٩ دينار"),
        ("i5", "الإجمالي المستحق: ٢١٩٫٥٩ دينار"),
    ]],
    # Normalised (Western digits, "." decimal) values a reader must recover.
    "numbers": ["2026/0042", "15/02/2026", "1", "12", "8.90", "106.80", "5", "9.00", "45.00", "500", "2", "18.75",
                "37.50", "189.30", "16%", "30.29", "219.59"],
    "fields": {
        "invoice_number": "2026/0042",
        "date": "15/02/2026",
        "customer": "مطعم البيدر",
        "subtotal": "189.30",
        "tax": "30.29",
        "total": "219.59",
    },
    "field_labels": {
        "invoice_number": "فاتورة مبيعات رقم",
        "date": "التاريخ",
        "customer": "العميل",
        "subtotal": "المجموع قبل الضريبة",
        "tax": "ضريبة المبيعات ١٦٪",
        "total": "الإجمالي المستحق",
    },
    "tables": [{
        "id": "invoice_lines",
        "header": ["الصنف", "الكمية", "سعر الوحدة", "المجموع"],
        "rows": [
            ["زيت زيتون بكر ممتاز ١ لتر", "١٢", "٨٫٩٠", "١٠٦٫٨٠"],
            ["تمر مجدول ١ كغم", "٥", "٩٫٠٠", "٤٥٫٠٠"],
            ["عسل سدر ٥٠٠ غرام", "٢", "١٨٫٧٥", "٣٧٫٥٠"],
        ],
    }],
}

DOCUMENTS = {d["id"]: d for d in (POLICY_AR, CONTRACT_AR, PRICE_LIST_XLSX, MIXED_REPORT, NEWSLETTER_2COL,
                                  HANDBOOK_EN, INVOICE_INDIC)}


def tables_of(doc):
    return {t["id"]: t for t in doc.get("tables", [])}


def paragraphs(doc):
    """[(pid, text)] in logical reading order (title first, tables as rows)."""
    out = [("title", doc["title"])]
    tables = tables_of(doc)
    if "sheets" in doc:
        for sheet, data in doc["sheets"].items():
            out.append((f"sheet:{sheet}", sheet))
            out.append((f"{sheet}:header", "\t".join(data["header"])))
            for n, row in enumerate(data["rows"]):
                out.append((f"{sheet}:r{n}", "\t".join(str(c) for c in row)))
        return out
    if "columns" in doc:
        for column in doc["columns"]:  # first list = right-hand (first-read) column
            out.extend(column)
        return out
    for page in doc["pages"]:
        for pid, text in page:
            if pid == "TABLE":
                table = tables[text]
                out.append((f"{table['id']}:header", " ".join(table["header"])))
                for n, row in enumerate(table["rows"]):
                    out.append((f"{table['id']}:r{n}", " ".join(row)))
            else:
                out.append((pid, text))
    return out


def reference_text(doc) -> str:
    return "\n".join(text for _, text in paragraphs(doc))


def passage(doc_id: str, pid: str) -> str:
    return dict(paragraphs(DOCUMENTS[doc_id]))[pid]


# --- Files built from the documents ------------------------------------------
# (file name, document id, kind) - kind says how build_corpus.py produces it.
FILES = [
    ("policy_ar.chromium.pdf", "policy_ar", "pdf_chromium"),          # native digital PDF (browser/Word-like producer)
    ("policy_ar.libreoffice.pdf", "policy_ar", "pdf_libreoffice"),    # native digital PDF (office suite)
    ("policy_ar.reportlab.pdf", "policy_ar", "pdf_reportlab"),        # KEEL's own PDF export technique
    ("policy_ar.scanned.pdf", "policy_ar", "pdf_scanned"),            # image-only (scanned) PDF
    ("policy_ar.docx", "policy_ar", "docx"),
    ("contract_ar.docx", "contract_ar", "docx"),                     # Word with a table
    ("contract_ar.pdf", "contract_ar", "pdf_chromium"),
    ("price_list_ar.xlsx", "price_list_ar", "xlsx"),
    ("mixed_report_q1.pdf", "mixed_report_q1", "pdf_chromium"),       # 3 pages, Arabic + English
    ("mixed_report_q1.docx", "mixed_report_q1", "docx"),
    ("newsletter_2col_ar.pdf", "newsletter_2col_ar", "pdf_chromium"),  # two columns
    ("handbook_en.pdf", "handbook_en", "pdf_chromium"),
    ("invoice_ar_indic.pdf", "invoice_ar_indic", "pdf_chromium"),     # Arabic-Indic digits + table
    ("invoice_ar_indic.scanned.pdf", "invoice_ar_indic", "pdf_scanned"),
]

# The knowledge base the RAG benchmark uploads (one file per document).
RAG_CORPUS = ["policy_ar.chromium.pdf", "contract_ar.docx", "price_list_ar.xlsx", "mixed_report_q1.pdf",
              "newsletter_2col_ar.pdf", "handbook_en.pdf", "invoice_ar_indic.pdf"]
# Same knowledge base, but the policy and invoice arrive as scans.
RAG_CORPUS_SCANNED = ["policy_ar.scanned.pdf", "contract_ar.docx", "price_list_ar.xlsx", "mixed_report_q1.pdf",
                      "newsletter_2col_ar.pdf", "handbook_en.pdf", "invoice_ar_indic.scanned.pdf"]

# --- RAG questions -------------------------------------------------------------
# kind: msa | levantine | en_about_ar | ar_about_en | mixed | synonym | diacritics | spelling | unanswerable
# gold: [(document id, paragraph id)] - a retrieved chunk is relevant when it
# contains the gold passage's `evidence` span (normalised), i.e. the answer is
# actually readable in it. facts: values a correct answer must state.
QUESTIONS = [
    {"id": "q01", "kind": "msa", "q": "كم تبلغ رسوم التوصيل داخل عمّان؟", "gold": [("policy_ar", "p2")], "evidence": "2.50 دينار", "facts": ["2.50"]},
    {"id": "q02", "kind": "levantine", "q": "قديش بياخد التوصيل لجوا عمان؟", "gold": [("policy_ar", "p1")], "evidence": "48 ساعة", "facts": ["48"]},
    {"id": "q03", "kind": "synonym", "q": "ما المدة المسموح بها لاسترجاع السلعة؟", "gold": [("policy_ar", "p3")], "evidence": "خلال 14 يوما", "facts": ["14"]},
    {"id": "q04", "kind": "levantine", "q": "إذا فتحت كيس أكل بقدر أرجعه؟", "gold": [("policy_ar", "p4")], "evidence": "المنتجات الغذائية المفتوحة", "facts": ["لا"]},
    {"id": "q05", "kind": "en_about_ar", "q": "What is the minimum order value for free delivery?", "gold": [("policy_ar", "p2")], "evidence": "40 دينار", "facts": ["40"]},
    {"id": "q06", "kind": "en_about_ar", "q": "How long does a refund take?", "gold": [("policy_ar", "p5")], "evidence": "خلال 7 ايام عمل", "facts": ["7"]},
    {"id": "q07", "kind": "msa", "q": "ما نسبة رسوم المعالجة على الطلبات المرتجعة المتأخرة؟", "gold": [("policy_ar", "p5")], "evidence": "5% رسوم معالجه", "facts": ["5%"]},
    {"id": "q08", "kind": "mixed", "q": "شو الـ website تبع المرتجعات؟", "gold": [("policy_ar", "p6")], "evidence": "alnada.example/returns", "facts": ["alnada.example/returns"]},
    {"id": "q09", "kind": "msa", "q": "متى يبدأ سريان سياسة الإرجاع الجديدة؟", "gold": [("policy_ar", "p7")], "evidence": "01/03/2026", "facts": ["01/03/2026"]},
    {"id": "q10", "kind": "levantine", "q": "لو وصلني الغرض خربان شو لازم أعمل؟", "gold": [("policy_ar", "p10")], "evidence": "خلال 24 ساعه", "facts": ["24"]},
    {"id": "q11", "kind": "msa", "q": "ما ساعات عمل خدمة العملاء؟", "gold": [("policy_ar", "p9")], "evidence": "9:00 صباحا", "facts": ["9:00", "6:00"]},
    {"id": "q12", "kind": "msa", "q": "ما سعر وحدة زيت الزيتون البكر الممتاز 1 لتر في عقد التوريد؟", "gold": [("contract_ar", "price_table:r1")], "evidence": "OL-1000", "facts": ["8.90"]},
    {"id": "q13", "kind": "en_about_ar", "q": "What is the late delivery penalty in the supplier contract?", "gold": [("contract_ar", "c4")], "evidence": "1.5%", "facts": ["1.5%"]},
    {"id": "q14", "kind": "msa", "q": "متى ينتهي عقد التوريد مع مؤسسة الزيتونة الذهبية؟", "gold": [("contract_ar", "c2")], "evidence": "31/12/2026", "facts": ["31/12/2026"]},
    {"id": "q15", "kind": "levantine", "q": "بعد كم يوم لازم ندفع للمورد؟", "gold": [("contract_ar", "c5")], "evidence": "خلال 30 يوما", "facts": ["30"]},
    {"id": "q16", "kind": "msa", "q": "ما الحد الأدنى للطلب لعبوة زيت الزيتون 3 لتر؟", "gold": [("contract_ar", "price_table:r2")], "evidence": "OL-3000", "facts": ["30"]},
    {"id": "q17", "kind": "msa", "q": "كم سعر القهوة العربية بالهيل؟", "gold": [("price_list_ar", "قائمة الأسعار:r1")], "evidence": "CF-02", "facts": ["6.50"]},
    {"id": "q18", "kind": "en_about_ar", "q": "How many units of Sidr honey are in stock?", "gold": [("price_list_ar", "قائمة الأسعار:r3")], "evidence": "HN-04", "facts": ["22"]},
    {"id": "q19", "kind": "levantine", "q": "قديش في عنا تمر مجدول بالمخزن؟", "gold": [("price_list_ar", "قائمة الأسعار:r2")], "evidence": "DT-03", "facts": ["60"]},
    {"id": "q20", "kind": "msa", "q": "كم بلغ إجمالي المبيعات في الربع الأول 2026؟", "gold": [("mixed_report_q1", "m1")], "evidence": "128,450", "facts": ["128,450"]},
    {"id": "q21", "kind": "en_about_ar", "q": "What was the sales growth in Q1 2026 compared with last year?", "gold": [("mixed_report_q1", "m1")], "evidence": "12.5%", "facts": ["12.5%"]},
    {"id": "q22", "kind": "ar_about_en", "q": "كم بلغت مبيعات Shopify؟", "gold": [("mixed_report_q1", "m2")], "evidence": "41,200", "facts": ["41,200"]},
    {"id": "q23", "kind": "mixed", "q": "ما هو الـ best-selling product في Q1؟", "gold": [("mixed_report_q1", "m3")], "evidence": "OL-1000", "facts": ["OL-1000"]},
    {"id": "q24", "kind": "synonym", "q": "كم أصبح متوسط قيمة سلة الشراء؟", "gold": [("mixed_report_q1", "m4")], "evidence": "21.15", "facts": ["21.15"]},
    {"id": "q25", "kind": "en_about_ar", "q": "What is the return rate after the policy update?", "gold": [("mixed_report_q1", "m5")], "evidence": "2.1%", "facts": ["2.1%"]},
    {"id": "q26", "kind": "levantine", "q": "مين المنافس اللي نزّل أسعار العسل؟", "gold": [("mixed_report_q1", "m6")], "evidence": "al-rayyan", "facts": ["Al-Rayyan"]},
    {"id": "q27", "kind": "msa", "q": "ما التوصية بخصوص مخزون عسل السدر قبل رمضان؟", "gold": [("mixed_report_q1", "m7")], "evidence": "20%", "facts": ["20%"]},
    {"id": "q28", "kind": "ar_about_en", "q": "كم صرفنا على التسويق في الربع الأول؟", "gold": [("mixed_report_q1", "m8")], "evidence": "6,300", "facts": ["6,300"]},
    {"id": "q29", "kind": "msa", "q": "أين افتتحت الشركة فرعها الجديد؟", "gold": [("newsletter_2col_ar", "a1")], "evidence": "اربد", "facts": ["إربد"]},
    {"id": "q30", "kind": "msa", "q": "كم موظفاً يعمل في فرع إربد؟", "gold": [("newsletter_2col_ar", "a3")], "evidence": "18 موظفا", "facts": ["18"]},
    {"id": "q31", "kind": "levantine", "q": "كل كم نقطة بتعطيني قسيمة؟", "gold": [("newsletter_2col_ar", "b2")], "evidence": "100 نقطه", "facts": ["100", "5"]},
    {"id": "q32", "kind": "en_about_ar", "q": "How many customers joined the loyalty program?", "gold": [("newsletter_2col_ar", "b3")], "evidence": "2,300", "facts": ["2,300"]},
    {"id": "q33", "kind": "ar_about_en", "q": "متى يتم جرد المستودع؟", "gold": [("handbook_en", "h1")], "evidence": "every thursday", "facts": ["Thursday", "4:00"]},
    {"id": "q34", "kind": "ar_about_en", "q": "ما درجة حرارة تخزين منتجات السلسلة الباردة؟", "gold": [("handbook_en", "h3")], "evidence": "between 2°c and 6°c", "facts": ["2", "6"]},
    {"id": "q35", "kind": "ar_about_en", "q": "قديش نقطة إعادة الطلب لزيت الزيتون OL-1000؟", "gold": [("handbook_en", "h4")], "evidence": "150 units", "facts": ["150"]},
    {"id": "q36", "kind": "ar_about_en", "q": "كم يوم إجازة سنوية يحصل عليها الموظف؟", "gold": [("handbook_en", "h5")], "evidence": "21 days", "facts": ["21"]},
    {"id": "q37", "kind": "msa", "q": "ما الإجمالي المستحق في فاتورة مطعم البيدر؟", "gold": [("invoice_ar_indic", "i5")], "evidence": "219.59", "facts": ["219.59"]},
    {"id": "q38", "kind": "en_about_ar", "q": "What is the sales tax amount on invoice 2026/0042?", "gold": [("invoice_ar_indic", "i4")], "evidence": "30.29", "facts": ["30.29"]},
    {"id": "q39", "kind": "diacritics", "q": "ما هي غايَةُ الشركةِ الأولى بحسبِ المديرِ العامّ؟", "gold": [("policy_ar", "p8")], "evidence": "رضا العميل", "facts": ["رضا العميل"]},
    {"id": "q40", "kind": "msa", "q": "ماذا قال المدير العام عن رضا العميل؟", "gold": [("policy_ar", "p8")], "evidence": "رضا العميل", "facts": ["رضا العميل"]},
    {"id": "q41", "kind": "spelling", "q": "ما هي اوقات دوام خدمه العملاء؟", "gold": [("policy_ar", "p9")], "evidence": "9:00 صباحا", "facts": ["9:00", "6:00"]},
    {"id": "q42", "kind": "unanswerable", "q": "ما هي سياسة الشركة بخصوص العمل عن بعد؟", "gold": [], "evidence": None, "facts": []},
    {"id": "q43", "kind": "unanswerable", "q": "What is the CEO's monthly salary?", "gold": [], "evidence": None, "facts": []},
]

# --- Marketing evaluation prompts ---------------------------------------------
# Product facts are the ONLY facts a draft may state; anything else (prices,
# discounts, origin, certifications) counts as fabricated.
MARKETING_PRODUCTS = [
    {"id": "olive_oil", "facts": "Product name: زيت زيتون بكر ممتاز 1 لتر (Extra Virgin Olive Oil 1L)\nBrand: Zaytouna Demo\nSKU: OL-1000\nSize: 1 litre"},
    {"id": "sidr_honey", "facts": "Product name: عسل سدر 500 غرام (Sidr Honey 500g)\nBrand: Al-Nada Demo\nSKU: HN-04\nSize: 500 g"},
]
MARKETING_PROMPTS = [
    {"id": "mk01", "product": "olive_oil", "language": "ar", "tone": "دافئ وعائلي", "strategy": "STORYTELLING", "platforms": ["INSTAGRAM"]},
    {"id": "mk02", "product": "olive_oil", "language": "ar", "tone": "باللهجة الأردنية العامية، قريب وودود", "strategy": "INFLUENCER_STYLE", "platforms": ["TIKTOK"]},
    {"id": "mk03", "product": "sidr_honey", "language": "ar", "tone": "فاخر ورسمي", "strategy": "BRAND_AWARENESS", "platforms": ["FACEBOOK"]},
    {"id": "mk04", "product": "sidr_honey", "language": "ar", "tone": "Ramadan seasonal, warm", "strategy": "URGENCY", "platforms": ["INSTAGRAM", "GOOGLE_ADS"]},
    {"id": "mk05", "product": "olive_oil", "language": "en", "tone": "bilingual-friendly, modern", "strategy": "SALES_DRIVEN", "platforms": ["INSTAGRAM", "FACEBOOK"]},
]

# --- RTL rendering cases ------------------------------------------------------
# Strings whose LOGICAL order must survive storage/API/export untouched.
RTL_CASES = [
    "سعر المنتج OL-1000 هو 8.90 دينار",
    "خصم 15% على طلبات https://alnada.example/shop",
    "التاريخ: 15/02/2026 – الفاتورة INV-2026-0042",
    "زيت زيتون (Extra Virgin) – 1 لتر",
    "الإجمالي المستحق: ٢١٩٫٥٩ دينار",
    "إِنَّ رِضا العَميلِ هو غايتُنا",
    "لا تُقبل الإعادة؛ هل لديك سؤال؟",
]
