#!/usr/bin/env python3
"""Moteur de prix PayezMoinsCher.

Télécharge les catalogues (flux produits) des enseignes qui nous ont acceptés sur Awin,
regroupe le même produit vendu par plusieurs enseignes (même code EAN) et écrit
data/offers.json, que le site lit pour afficher les vrais prix.

Utilisation :
  AWIN_FEED_KEY=... python3 scripts/build_offers.py            # téléchargement réel
  python3 scripts/build_offers.py --csv flux1.csv [flux2.csv]   # test sur des fichiers locaux
"""
import argparse, csv, datetime, gzip, io, json, os, re, sys, urllib.request

csv.field_size_limit(10_000_000)
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "offers.json")
MAX_PRODUCTS = 3000

# Nom de l'annonceur sur Awin -> nom affiché sur le site (doit correspondre aux noms du site)
SITES = {"darty": "Darty", "fnac": "Fnac", "cdiscount": "Cdiscount", "boulanger": "Boulanger",
         "conforama": "Conforama", "but": "But", "electro depot": "Electro Dépôt", "electrodepot": "Electro Dépôt",
         "amazon": "Amazon"}
# Annonceurs à ignorer même s'ils contiennent un nom d'enseigne
SKIP = ("spectacles", "pro fr", "mobile", "voyage")

# Mots-clés de catégorie -> (cat du site, libellé)
CATS = [
    (r"lave[- ]linge|machine à laver", "gros", "Lave-linge"),
    (r"sèche[- ]linge", "gros", "Sèche-linge"),
    (r"lave[- ]vaisselle", "gros", "Lave-vaisselle"),
    (r"réfrig|frigo|congélateur", "gros", "Réfrigérateur"),
    (r"four|cuisinière|plaque|table de cuisson|hotte", "gros", "Cuisson"),
    (r"micro[- ]ondes", "petit", "Micro-ondes"),
    (r"aspirateur", "petit", "Aspirateur"),
    (r"friteuse|airfryer|air fryer", "petit", "Friteuse sans huile"),
    (r"cafeti|expresso|espresso|machine à café", "petit", "Café"),
    (r"robot|blender|mixeur|bouilloire|grille[- ]pain", "petit", "Cuisine"),
    (r"télévi|\btv\b|oled|qled", "tv", "Téléviseur"),
    (r"barre de son|enceinte|casque|écouteur|home cinéma", "tv", "Son"),
    (r"console|playstation|ps5|xbox|switch", "tech", "Console"),
    (r"ordinateur|pc portable|laptop|macbook", "tech", "Ordinateur"),
    (r"smartphone|iphone|téléphone mobile", "tech", "Smartphone"),
    (r"tablette|ipad", "tech", "Tablette"),
]

def site_of(merchant):
    m = merchant.lower().replace("-", " ").replace("é", "e")
    if any(s in m for s in SKIP):
        return None
    for key, name in SITES.items():
        if m.startswith(key):
            return name
    return None

def pick(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v.strip()
    return ""

def money(v):
    v = (v or "").replace("€", "").replace("EUR", "").replace(" ", "").replace(",", ".")
    try:
        return round(float(v), 2)
    except ValueError:
        return None

def ean_of(row):
    e = re.sub(r"\D", "", pick(row, "ean", "product_GTIN", "upc"))
    if len(e) == 12:
        e = "0" + e
    return e if len(e) == 13 else None

def category(row):
    text = " ".join([pick(row, "category_name"), pick(row, "merchant_category"),
                     pick(row, "merchant_product_category_path"), pick(row, "product_name")]).lower()
    for pattern, cat, label in CATS:
        if re.search(pattern, text):
            return cat, label
    return None

def in_stock(row):
    v = pick(row, "in_stock", "is_for_sale", "stock_status").lower()
    return v not in ("0", "false", "no", "non", "out of stock", "outofstock")

def read_rows(fh, merchant_hint=None):
    for row in csv.DictReader(fh):
        if merchant_hint and not row.get("merchant_name"):
            row["merchant_name"] = merchant_hint
        yield row

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PayezMoinsCher/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return io.StringIO(data.decode("utf-8", errors="replace"))

def awin_sources(key):
    """Flux des annonceurs qui nous ont acceptés (Membership Status = active)."""
    lst = download(f"https://productdata.awin.com/datafeed/list/apikey/{key}")
    for row in csv.DictReader(lst):
        status = (row.get("Membership Status") or "").lower()
        name = row.get("Advertiser Name") or ""
        if status in ("active", "joined") and site_of(name) and (row.get("Language") or "fr").lower().startswith("fr"):
            yield name, row["URL"]

def build(rows):
    products = {}
    for row in rows:
        site = site_of(pick(row, "merchant_name"))
        ean = ean_of(row)
        price = money(pick(row, "search_price", "price", "store_price"))
        link = pick(row, "aw_deep_link", "deep_link")
        if not (site and ean and price and link) or not in_stock(row):
            continue
        cat = category(row)
        if not cat:
            continue
        p = products.setdefault(ean, {"ean": ean, "name": pick(row, "product_name"), "brand": pick(row, "brand_name"),
                                      "model": pick(row, "model_number", "mpn", "product_model"), "cat": cat[0], "catLabel": cat[1],
                                      "image": pick(row, "merchant_image_url", "large_image", "image_url", "aw_image_url"), "offers": {}})
        ship = money(pick(row, "delivery_cost"))
        old = p["offers"].get(site)
        if not old or price < old["price"]:
            p["offers"][site] = {"site": site, "price": price, "ship": ship if ship is not None else None, "url": link}
    out = []
    for p in products.values():
        p["offers"] = sorted(p["offers"].values(), key=lambda o: o["price"])
        out.append(p)
    # D'abord les produits vendus par le plus d'enseignes : c'est là que la comparaison est utile.
    out.sort(key=lambda p: (-len(p["offers"]), p["name"]))
    return out[:MAX_PRODUCTS]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="*", help="fichiers CSV locaux (test)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    rows = []
    if a.csv:
        for f in a.csv:
            with open(f, encoding="utf-8") as fh:
                rows.extend(read_rows(fh))
    else:
        key = os.environ.get("AWIN_FEED_KEY")
        if not key:
            print("AWIN_FEED_KEY manquant : rien à télécharger, data/offers.json inchangé.", file=sys.stderr)
            return
        for name, url in awin_sources(key):
            print("Flux :", name, file=sys.stderr)
            rows.extend(read_rows(download(url), merchant_hint=name))
    products = build(rows)
    data = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "products": products}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(products)} produits, {sum(len(p['offers']) for p in products)} offres -> {a.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
