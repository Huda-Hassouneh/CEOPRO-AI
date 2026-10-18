"""Per-plan operating cost and gross-margin model for docs/PLAN_LIMITS_FEASIBILITY.md.
Unit prices are inputs to re-check against each vendor before launch; run with python3."""
# Unit prices (USD). Sources noted in the report.
GROQ_IN, GROQ_OUT = 0.075/1e6, 0.30/1e6
PLACES_DETAILS_ATM = 25/1000          # Place Details Enterprise+Atmosphere
PLACES_SEARCH_ENT = 35/1000           # Nearby/Text Search Enterprise
APIFY_PLACE = 4/1000 + 2/1000         # place + detail page (Starter tier)
APIFY_REVIEW = 0.50/1000
WEB_SEARCH = 5/1000                   # Brave-class replacement for CSE
IMG_LOW, IMG_HIGH = 0.003, 0.02
R2_GB = 0.015
NEON_GB = 0.35
PLANS = {
 "Starter":    dict(price=55,  comp=10,  reviews=5000,   tokens=100_000,   searches=100, imgs=20,  storage=1,  uploads_gb=0.05, refresh_per_month=4.33),
 "Growth":     dict(price=140, comp=30,  reviews=25000,  tokens=500_000,   searches=500, imgs=100, storage=10, uploads_gb=0.5,  refresh_per_month=30),
 "Enterprise": dict(price=350, comp=100, reviews=100000, tokens=2_000_000, searches=500, imgs=150, storage=50, uploads_gb=2.0,  refresh_per_month=30),
}
def stripe(p, worst):  # card + intl (+ conversion) + Billing 0.7%
    return p*(0.029+0.015+(0.01 if worst else 0)+0.007)+0.30
def costs(p, worst):
    c = {}
    refreshes = p["comp"]*p["refresh_per_month"]
    c["competitor refresh"] = refreshes*(PLACES_DETAILS_ATM if worst else APIFY_PLACE)
    disc_run = 12*PLACES_SEARCH_ENT + 120*4/1000 + 4*WEB_SEARCH
    c["area discovery (weekly)"] = 4.33*(disc_run if worst else 120*4/1000 + 4*WEB_SEARCH)
    rev = p["reviews"] if worst else p["comp"]*20
    c["review collection"] = rev*APIFY_REVIEW
    t = p["tokens"]*(1 if worst else 0.3)
    c["AI answers (tokens)"] = t*(GROQ_OUT if worst else 0.94*GROQ_IN+0.06*GROQ_OUT)
    c["web research"] = p["searches"]*(1 if worst else 0.2)*WEB_SEARCH
    c["images"] = p["imgs"]*(IMG_HIGH if worst else 0.25*IMG_LOW)
    c["file storage"] = p["storage"]*(1 if worst else 0.25)*R2_GB
    # DB growth after 12 months: reviews 1.5KB/row, doc chunks ~ 0.4 GB per GB uploaded
    db_gb = (12*rev*1.5e3/1e9) + (12*p["uploads_gb"]*0.4 if worst else 0.05) + 0.1
    c["database storage (yr-1 end)"] = db_gb*NEON_GB
    c["payment processing"] = stripe(p["price"], worst)
    return c
FIXED = {"lean": 80, "robust": 247}
for name, p in PLANS.items():
    for worst in (False, True):
        c = costs(p, worst); var = sum(c.values())
        label = "FULL QUOTA (worst)" if worst else "normal"
        print(f"\n== {name} ${p['price']} — {label}")
        for k, v in c.items(): print(f"   {k:30} ${v:8.2f}")
        print(f"   {'variable total':30} ${var:8.2f}")
        for price, tag in ((p["price"], "monthly"), (p["price"]*0.8, "6-month (-20%)")):
            vv = var - stripe(p["price"], worst) + stripe(price, worst)
            for n in (10, 50):
                for f in ("lean", "robust"):
                    alloc = FIXED[f]/n
                    m = (price - vv - alloc)/price
                    print(f"   {tag:15} {n:3} customers {f:6}: cost ${vv+alloc:7.2f}  gross margin {m*100:5.1f}%")
