"""
Builds the demo companies' business documents (PDF) that the seeder uploads
to each company's AI assistant knowledge base. The facts in them (fees,
windows, terms, prices) are consistent with profiles.py, so assistant answers
can be checked against them.

Needs reportlab (a dev-only tool, not an application dependency); the built
PDFs are committed under documents/ so seeding never needs it.

Usage: python -m scripts.demo_companies.build_documents
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from scripts.demo_companies.profiles import COMPANIES

OUT = Path(__file__).parent / "documents"

DOCS = {
    "zaytouna": {
        "company_profile": ("Zaytouna Fine Foods - Company Profile", [
            "Zaytouna Fine Foods is a family-owned specialty food retailer founded in 2014 in Amman, Jordan, by Rania Haddad. "
            "We operate two stores - Jabal Amman (Rainbow Street) and Sweifieh - and an online shop delivering across Jordan.",
            "We source extra virgin olive oil directly from 14 partner farms in Ajloun and Jerash. Our oil is cold-pressed within "
            "24 hours of harvest. The new-season harvest arrives every November, when we launch our Early Harvest oil.",
            "Product range: olive oil (1L, 500ml, 4L tins, Early Harvest 750ml), za'atar and spices, Medjool dates from the Jordan Valley, "
            "Sidr and wildflower honey from Ajloun Apiaries, labneh and Nabulsi cheese, grains (freekeh, bulgur, maftoul), Arabic and "
            "Turkish coffee, pantry items and olive oil soap.",
            "Opening hours: Saturday-Thursday 9:00-22:00, Friday 14:00-22:00. During Ramadan stores open 10:00-17:00 and 20:30-01:00.",
            "Customer service: WhatsApp +962 79 000 0000, email care@zaytouna-demo.example. Team of 11 people.",
        ]),
        "returns_policy": ("Returns & Refunds Policy", [
            "Unopened packaged products can be returned within 14 days of purchase with the receipt or order number for a full refund.",
            "Fresh and chilled products (labneh, cheese) cannot be returned unless they are damaged or past their date on delivery; "
            "report this within 24 hours with a photo and we replace the item or refund it.",
            "Refunds are made to the original payment method within 5 business days. Cash-on-delivery orders are refunded by "
            "bank transfer or store credit.",
            "Gift hampers are final sale once delivered, except for damaged items.",
        ]),
        "delivery_policy": ("Delivery Policy", [
            "Amman: same-day delivery for orders placed before 14:00; fee 2.000 JOD, free for orders above 25.000 JOD.",
            "Zarqa and Salt: next-day delivery, fee 3.500 JOD. Irbid, Madaba and Aqaba: 2-3 business days, fee 4.500 JOD.",
            "We deliver Saturday to Thursday. Friday orders are delivered on Saturday.",
            "Payment: cash on delivery, card on delivery, or online card payment. During Ramadan, deliveries run until one hour before iftar.",
        ]),
        "wholesale_terms": ("Wholesale & Corporate Orders", [
            "Restaurants, hotels and offices can open a wholesale account with a minimum order of 150.000 JOD.",
            "Wholesale discounts: 8% on orders above 150 JOD, 12% above 400 JOD, 15% above 1,000 JOD.",
            "Corporate Ramadan and Eid gift hampers can be customised from 25 units, with orders confirmed at least 10 days in advance.",
            "Payment terms: 50% deposit, balance on delivery; approved accounts get 30-day terms.",
        ]),
        "supplier_price_list": ("Supplier Price List 2026 (cost prices, confidential)", [
            "Olive oil 1L bottle: 6.200 JOD (from January 2026). 500ml: 3.600 JOD. 4L tin: 22.000 JOD. Early Harvest 750ml: 8.100 JOD.",
            "Medjool dates 1kg: 4.800 JOD; gift box 500g: 3.400 JOD. Sidr honey 500g: 12.500 JOD. Za'atar 250g: 1.400 JOD.",
            "Our olive oil supplier raised prices by 6% in January 2026 after a weaker harvest; we raised the 1L shelf price from 8.950 to 9.500 JOD.",
        ]),
    },
    "atlas": {
        "fashion_returns": ("Atlas Couture - Conditions de retour et d'échange", [
            "Les articles peuvent être échangés sous 15 jours, avec étiquettes et ticket de caisse. Les remboursements sont possibles sous 7 jours.",
            "Les caftans sur mesure et les articles soldés ne sont ni repris ni échangés. Les retouches sont offertes pour tout caftan acheté.",
            "Livraison au Maroc : 35 MAD (gratuite dès 1 000 MAD), 2 à 4 jours ouvrés. Livraison en France : 120 MAD, 5 à 8 jours.",
            "Boutique : 24 rue Moulay Youssef, Casablanca. Ouverte du lundi au samedi de 10h à 20h.",
        ]),
        "fashion_size_guide": ("Guide des tailles Atlas Couture", [
            "S correspond au 36, M au 38-40, L au 42. Les caftans existent en M, L et taille unique pour le modèle mariage.",
            "Nos robes en lin sont coupées ample : en cas de doute, choisissez la taille inférieure.",
            "Le caftan Ivoire mariage est réalisé sur commande en 3 semaines, acompte de 50 % à la commande.",
        ]),
    },
    "beit": {
        "restaurant_menu_allergens": ("Beit Al Shawarma - Menu & Allergen Information", [
            "Chicken shawarma is marinated for 12 hours in garlic, yoghurt and seven spices; beef shawarma uses Australian beef.",
            "Allergens: our garlic sauce (toum) contains no dairy; tahini sauce contains sesame; kunafa contains gluten, dairy and nuts.",
            "Delivery through our own website and the major delivery apps within Dubai Marina, JLT and Al Barsha, 45 minutes average.",
            "Opening hours: daily 11:00-02:00. During Ramadan: 17:30 (iftar) until 03:00, with iftar boxes pre-ordered by 15:00.",
            "Catering: family meal box serves 4 people (129 AED); events from 30 people with 48 hours notice.",
        ]),
    },
    "nour": {
        "salon_booking_policy": ("Nour Beauty Lounge - Booking & Cancellation Policy", [
            "Appointments can be booked by WhatsApp or our website. Please arrive 10 minutes early.",
            "Cancellations less than 6 hours before the appointment are charged 50% of the service price. No-shows are charged in full.",
            "Bridal packages require a 30% deposit and a trial session booked at least 2 weeks before the wedding.",
            "Opening hours: Saturday-Thursday 10:00-22:00, Friday 16:00-23:00. Before Eid we open until midnight.",
        ]),
        "salon_price_list": ("Nour Beauty Lounge - Price List 2026", [
            "Haircut & styling 170 SAR (from January 2026, previously 150 SAR). Blow-dry 90 SAR. Full colour 450 SAR. Keratin 900 SAR.",
            "Classic facial 280 SAR. Hydrafacial 550 SAR (launched August 2025). Manicure & pedicure 180 SAR. Gel nails 220 SAR.",
            "Bridal package 3,500 SAR: hair, makeup, nails and a trial session.",
            "Retail: Argan repair shampoo 95 SAR, Argan mask 120 SAR, Vitamin C serum 210 SAR, SPF 50 sunscreen 135 SAR.",
        ]),
    },
    "petra": {
        "b2b_terms": ("Petra Industrial Supplies - Terms of Sale", [
            "Prices are per metre, kilogram, ton, bag or box as stated, excluding 16% sales tax, delivered ex-works Sahab Industrial City.",
            "Volume discounts: 3% from 5,000 JOD per order, 5% from 15,000 JOD, 7-10% for annual framework agreements.",
            "Payment terms: 30 days for approved contractors, 60 days for government tenders. Late payments carry 1% per month.",
            "Delivery within Amman and Zarqa in 48 hours with our own trucks (free above 2,000 JOD); export to Iraq and Palestine via Karama and King Hussein crossings.",
            "Custom fabrication is billed at 35 JOD per hour with a minimum of 2 hours.",
        ]),
        "industrial_catalog": ("Product Catalogue 2026", [
            "Galvanized steel pipe 2 inch: 7.240 JOD per metre (from November 2025). PVC pipe 110mm: 2.375 JOD per metre.",
            "Steel rebar 12mm: 529.000 JOD per ton (May 2026 price, follows the international steel index).",
            "Galvanized sheet 1.2mm: 1.012 JOD per kg. Portland cement 50kg bag: 4.320 JOD.",
            "Hex bolt M12 box of 100: 14.500 JOD. Anchor bolt M16 box of 50: 21.750 JOD. Brass gate valve 2 inch: 18.400 JOD.",
        ]),
    },
    "bytefix": {
        "electronics_warranty": ("ByteFix Electronics - Warranty & Repair Policy", [
            "New phones carry the official manufacturer warranty of 12 months; accessories 6 months against manufacturing defects.",
            "Repairs (screen, battery) carry a 90-day warranty on the replaced part. Water-damage repairs carry no warranty.",
            "Diagnostics cost 300 EGP and are deducted from the repair price if the customer goes ahead with the repair.",
            "Prices follow the official distributor price lists and were raised in October 2025 and April 2026 after currency changes.",
            "Branches: Nasr City and Heliopolis, Cairo. Open daily 11:00-23:00.",
        ]),
    },
    "clarity": {
        "consulting_services": ("Clarity Conseil - Offre de services et conditions", [
            "Conseil stratégique facturé à l'heure : 155 EUR HT depuis janvier 2026 (140 EUR auparavant), par tranches de 30 minutes.",
            "Ateliers de transformation : 1 800 EUR HT la journée. Audit des processus : forfait de 6 500 EUR HT.",
            "Accompagnement mensuel : 2 400 EUR HT par mois, engagement de 6 mois minimum.",
            "Paiement à 30 jours fin de mois. Clients principaux : Lumen Retail SAS, Atelier Verde, Groupe Hexa.",
        ]),
    },
}


def build() -> list:
    OUT.mkdir(exist_ok=True)
    styles = getSampleStyleSheet()
    written = []
    for company in COMPANIES:
        for key, (title, paragraphs) in DOCS.get(company.key, {}).items():
            path = OUT / f"{company.key}__{key}.pdf"
            doc = SimpleDocTemplate(str(path), pagesize=A4, title=title, author=company.business_name)
            story = [Paragraph(company.business_name, styles["Title"]), Paragraph(title, styles["Heading2"]), Spacer(1, 10)]
            for text in paragraphs:
                story += [Paragraph(text, styles["BodyText"]), Spacer(1, 8)]
            story.append(Table([["Document owner", company.owner_name], ["Last reviewed", "September 2026"]]))
            doc.build(story)
            written.append(path.name)
    return written


if __name__ == "__main__":
    print("\n".join(build()))
