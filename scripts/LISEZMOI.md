# Moteur de prix

`build_offers.py` télécharge chaque jour les flux produits Awin des enseignes qui ont accepté PayezMoinsCher,
regroupe le même produit (même code EAN) vendu par plusieurs enseignes et écrit `data/offers.json`.
Le site lit ce fichier : quand il contient des produits, les fiches affichent les vrais prix et le coût réel.

- Mise à jour automatique : `.github/workflows/prix.yml`, tous les jours à 4 h (heure UTC).
- Clé nécessaire : secret GitHub `AWIN_FEED_KEY` (Awin > Outils > Create-a-Feed, « clé API des flux »).
- Test local : `python3 scripts/build_offers.py --csv scripts/test/flux-test.csv --out /tmp/test.json`
  (`flux-test.csv` contient des produits fictifs, uniquement pour tester ; ne jamais le publier).
