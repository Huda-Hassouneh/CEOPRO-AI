"""Social conversation test sets, written 2026-11-06 BEFORE any change to conversation.py in this round.
kind: "social" (answered warmly, no business figures) | "business" (goes to the business path).
q_kept: for "greeting/polite opener + question", the business question must survive (remainder non-empty).
SEALED: never used to change code; aggregate scoring only, after approval. UNREVIEWED by a native speaker."""


def s(q, kind, **kw):
    return {"q": q, "kind": kind, **kw}


SOCIAL_DEV = [
    s("مرحبتين", "social"), s("هلا هلا", "social"), s("صباح الخير عليكم", "social"), s("مسا النور", "social"),
    s("يعطيك العافية يا رب", "social"), s("تسلم يا معلم", "social"), s("مشكورين يا شباب", "social"),
    s("لو سمحت", "social"), s("من فضلك", "social"), s("excuse me", "social"),
    s("بشوفك بكرا", "social"), s("يلا بشوفك", "social"), s("منشوفك بعدين", "social"), s("سلام يا غالي", "social"),
    s("شو بتعرف تعمل؟", "social"), s("شو بتقدر تعمل الي", "social"), s("what are you capable of", "social"),
    s("والله انك رائع", "social"), s("انت ممتاز", "social"), s("you're awesome", "social"), s("برافو عليك", "social"),
    s("الحمدلله", "social"), s("الحمد لله تمام", "social"), s("بخير الحمدلله", "social"),
    s("👍", "social"), s("🙏", "social"), s("😂😂", "social"), s("👋", "social"),
    s("آسف عالإزعاج", "social"), s("sorry for the trouble", "social"),
    s("thanks habibi", "social"), s("tislam ya ghali", "social"),
    s("لو سمحت قديش بعنا امبارح؟", "business", q_kept=True), s("من فضلك اعطيني المبيعات", "business", q_kept=True),
    s("please show me last month's sales", "business", q_kept=True), s("مرحبا بدي اعرف الستوك", "business", q_kept=True),
    s("يعطيك العافية، كم طلبية اجت اليوم؟", "business", q_kept=True), s("هاي، شو اكتر منتج بنبيعه؟", "business", q_kept=True),
    s("شكرا، وقديش الربح؟", "business", q_kept=True), s("تمام، والشهر اللي قبله؟", "business", q_kept=True),
    s("الحمدلله، قديش ضل طحينة؟", "business", q_kept=True),
    s("بدي مساعدة بالأسعار", "business"), s("ساعدني افهم المبيعات", "business"),
    s("رائع، بس ليش نزل البيع؟", "business", q_kept=True), s("سلامتك، شو وضع المخزون؟", "business", q_kept=True),
]

SOCIAL_VAL = [
    s("اهلا وسهلا", "social"), s("صباح الورد", "social"), s("يسعد مساك", "social"), s("كيفك اليوم يا غالي", "social"),
    s("الله يسلمك", "social"), s("مشكور كتير", "social"), s("لو تكرمت", "social"), s("ممكن مساعدة؟", "social"),
    s("بشوفك على خير", "social"), s("تصبحوا على خير", "social"), s("انت مين بالزبط؟", "social"),
    s("شو الاشيا اللي بتقدر تساعدني فيها؟", "social"), s("يا سلام عليك", "social"), s("انت شاطر", "social"),
    s("great job", "social"), s("الحمدلله على كل حال", "social"), s("❤️", "social"), s("👌", "social"),
    s("معلش اتأخرت", "social"), s("my bad", "social"), s("yalla bye", "social"), s("merci ktir", "social"),
    s("لو سمحت قديش سعر العسل؟", "business", q_kept=True), s("ممكن تعطيني مبيعات اليوم؟", "business", q_kept=True),
    s("hello, what's my revenue this month?", "business", q_kept=True), s("صباح الخير، في طلبيات جديدة؟", "business", q_kept=True),
    s("مشكور، وشو عن الزيت؟", "business", q_kept=True), s("ممتاز، بس قديش الكلفة؟", "business", q_kept=True),
    s("الحمدلله، شو اخبار البيع؟", "business", q_kept=True), s("تمام، اعطيني الربح كمان", "business", q_kept=True),
    s("ساعدني بالتسعير", "business"), s("بدي اعرف مين المنافسين", "business"),
]

