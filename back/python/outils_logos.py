"""Récupération des logos d'entreprise. OUTIL MANUEL, hors pipeline.

Rien ici ne tourne pendant une génération : les logos sont téléchargés une
fois, relus, puis versionnés. Un logo est une marque déposée — il n'a pas à
arriver dans une vidéo publiée par un appel réseau que personne n'a regardé.

Source : https://logos.hunter.io/{domaine} — gratuit, sans clé, 404 propre sur
un domaine inconnu. Limites mesurées : 128 px de côté maximum (aucun
paramètre de taille), fond blanc opaque, et certaines réponses en AVIF.
D'où le traitement ci-dessous.

Usage :
    python outils_logos.py --deviner       complète domaines.json en testant
                                           plusieurs candidats par entreprise
    python outils_logos.py --telecharger   récupère et traite les manquants
    python outils_logos.py --trier         ecarte photos et favicons
    python outils_logos.py --alleger       ramene les logos a 256 px
    python outils_logos.py --planche       planche de contact pour relecture
    python outils_logos.py --etat          ce qui manque encore
"""
import argparse
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICI = Path(__file__).parent
SUJETS = ICI / "subjects_de.json"
LOGOS = ICI / "logos"
TABLE = LOGOS / "domaines.json"
POLICE = ICI / "fonts" / "Montserrat-ExtraBold.ttf"

SOURCE = "https://logos.hunter.io/{}"
ENTETES = {"User-Agent": "Mozilla/5.0"}

# Suffixes essayes dans l'ordre. Les societes allemandes cotees sont souvent
# en .de, et beaucoup portent un suffixe juridique (AG, SE) absent du domaine.
SUFFIXES = (".com", ".de")


def _nettoie(nom):
    n = nom.lower().strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
                 ("&", "and"), ("+", ""), ("'", ""), (".", "")):
        n = n.replace(a, b)
    return n


def candidats(nom):
    """Domaines plausibles pour une entreprise, du plus au moins probable."""
    base = _nettoie(nom)
    mots = base.split()
    # « Porsche SE », « Deutsche Pfandbriefbank AG » : le suffixe juridique
    # ne fait presque jamais partie du domaine.
    sans_forme = [m for m in mots if m not in ("ag", "se", "sa", "nv", "plc", "kgaa")]
    formes = []
    for pieces in (mots, sans_forme):
        if not pieces:
            continue
        formes += ["".join(pieces), "-".join(pieces)]
        if len(pieces) > 1:
            formes.append(pieces[0])            # « Carl Zeiss Meditec » -> carl
            formes.append(pieces[-1])           # « Adler Group » -> group (rare)
    vus, sortie = set(), []
    for forme in formes:
        for suffixe in SUFFIXES:
            d = forme + suffixe
            if d not in vus and len(forme) > 1:
                vus.add(d)
                sortie.append(d)
    return sortie


def interroge(domaine):
    """(octets, type) si Hunter connait ce domaine, sinon None."""
    try:
        req = urllib.request.Request(SOURCE.format(domaine), headers=ENTETES)
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(), r.headers.get("Content-Type", "").split(";")[0]
    except urllib.error.HTTPError:
        return None
    except Exception as e:
        print(f"    reseau ({type(e).__name__}) sur {domaine}")
        return None


def en_image(brut, ctype, travail):
    """AVIF -> PNG via FFmpeg, deja present pour le montage."""
    if ctype != "image/avif":
        return Image.open(io.BytesIO(brut))
    src, dst = travail.with_suffix(".avif"), travail.with_suffix(".conv.png")
    src.write_bytes(brut)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), str(dst)],
                       capture_output=True)
    src.unlink(missing_ok=True)
    if r.returncode != 0 or not dst.exists():
        raise ValueError("conversion AVIF impossible")
    im = Image.open(dst).copy()
    dst.unlink(missing_ok=True)
    return im


def detoure(im, tolerance=26):
    """Rend transparent le blanc du POURTOUR.

    Depuis les quatre coins uniquement : un remplissage global effacerait
    aussi les blancs INTERIEURS du dessin - le « BAYER » en reserve dans son
    cercle disparaitrait.
    """
    im = im.convert("RGBA")
    px = im.load()
    l, h = im.size
    vu = set()
    pile = [(0, 0), (l - 1, 0), (0, h - 1), (l - 1, h - 1)]
    while pile:
        x, y = pile.pop()
        if (x, y) in vu or not (0 <= x < l and 0 <= y < h):
            continue
        vu.add((x, y))
        r, v, b, a = px[x, y]
        if a == 0 or min(r, v, b) < 255 - tolerance:
            continue
        px[x, y] = (r, v, b, 0)
        pile += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return im


def sujets():
    return json.loads(SUJETS.read_text(encoding="utf-8"))


def table():
    if TABLE.exists():
        return json.loads(TABLE.read_text(encoding="utf-8"))
    return {}


def ecrit_table(t):
    LOGOS.mkdir(exist_ok=True)
    TABLE.write_text(json.dumps(t, ensure_ascii=False, indent=2, sort_keys=True),
                     encoding="utf-8")


def fichier(symbole):
    return LOGOS / (symbole.replace(".", "_") + ".png")


# --- commandes ---------------------------------------------------------

def deviner():
    """Cherche un domaine par entreprise en testant les candidats.

    Un domaine qui repond n'est PAS une preuve qu'il s'agit de la bonne
    societe : « group.com » existe et n'a rien a voir avec Adler Group. D'ou
    la planche de contact, qui reste la seule verification serieuse.
    """
    t = table()
    manquants = []
    for s in sujets():
        sym, nom = s["symbole"], s["nom"]
        if t.get(sym):
            continue
        trouve = None
        for d in candidats(nom):
            if interroge(d):
                trouve = d
                break
            time.sleep(0.15)
        if trouve:
            t[sym] = trouve
            print(f"  {sym:<12} {nom:<26} -> {trouve}")
        else:
            t[sym] = ""
            manquants.append((sym, nom))
            print(f"  {sym:<12} {nom:<26} -> A COMPLETER A LA MAIN")
    ecrit_table(t)
    print(f"\n{len(t) - len(manquants)}/{len(t)} domaines trouves.")
    if manquants:
        print(f"\n{len(manquants)} a completer dans {TABLE.name} :")
        for sym, nom in manquants:
            print(f'  "{sym}": "",   // {nom}')


def telecharger():
    t = table()
    if not t:
        print("Table vide : lancer --deviner d'abord.")
        return 1
    LOGOS.mkdir(exist_ok=True)
    ok = rates = passes = 0
    for s in sujets():
        sym = s["symbole"]
        domaine = t.get(sym, "")
        if fichier(sym).exists():
            passes += 1
            continue
        if not domaine:
            rates += 1
            continue
        reponse = interroge(domaine)
        if not reponse:
            print(f"  {sym:<12} {domaine:<30} introuvable")
            rates += 1
            continue
        brut, ctype = reponse
        try:
            im = detoure(en_image(brut, ctype, LOGOS / sym.replace(".", "_")))
        except Exception as e:
            print(f"  {sym:<12} {domaine:<30} {e}")
            rates += 1
            continue
        im.save(fichier(sym))
        opaque = 100 * sum(1 for p in im.getdata() if p[3] > 0) / (im.width * im.height)
        print(f"  {sym:<12} {domaine:<30} {im.width}x{im.height}, {opaque:.0f}% opaque")
        ok += 1
        time.sleep(0.15)
    print(f"\n{ok} telecharges, {passes} deja presents, {rates} sans logo.")


def planche():
    """Toutes les vignettes sur une image, pour relecture d'un coup d'oeil.

    C'est LA verification qui compte : elle montre les logos attribues a la
    mauvaise societe, ce qu'aucun controle automatique ne peut faire.
    """
    presents = [(s["symbole"], s["nom"]) for s in sujets() if fichier(s["symbole"]).exists()]
    if not presents:
        print("Aucun logo a montrer.")
        return 1
    colonnes, case, marge = 6, 150, 12
    lignes = (len(presents) + colonnes - 1) // colonnes
    img = Image.new("RGB", (colonnes * case, lignes * (case + 28)), (14, 15, 20))
    d = ImageDraw.Draw(img)
    police = ImageFont.truetype(str(POLICE), 13)
    for i, (sym, nom) in enumerate(presents):
        cx, cy = (i % colonnes) * case, (i // colonnes) * (case + 28)
        logo = Image.open(fichier(sym)).convert("RGBA")
        cote = case - 2 * marge
        ratio = cote / max(logo.size)
        petit = logo.resize((max(1, int(logo.width * ratio)),
                             max(1, int(logo.height * ratio))), Image.LANCZOS)
        img.paste(petit, (cx + (case - petit.width) // 2,
                          cy + (case - petit.height) // 2), petit)
        etiquette = nom if d.textlength(nom, font=police) < case - 8 else nom[:18] + "…"
        d.text((cx + (case - d.textlength(etiquette, font=police)) / 2, cy + case + 4),
               etiquette, font=police, fill=(210, 212, 220))
    sortie = LOGOS / "_planche.png"
    img.save(sortie)
    print(f"{len(presents)} logos -> {sortie}")


def _diagnostic(im):
    """Pourquoi cette image n'est pas un logo, ou None si elle l'est.

    Hunter renvoie l'image de PARTAGE SOCIAL du site quand il n'a pas de
    logo : sur 95 sujets, ça donne des photos de bâtiments, des voitures et
    des favicons étirés. Trois mesures suffisent à les écarter :

      - taille native : en dessous de 64 px c'est un favicon, illisible une
        fois agrandi ;
      - richesse chromatique : un logo tient en une poignée de teintes, une
        photo en compte des milliers ;
      - image vide : quelques pixels utiles, ou une seule couleur.
    """
    if max(im.size) < 64:
        return f"favicon {im.width}x{im.height}"
    rgb = im.convert("RGB").resize((64, 64), Image.LANCZOS)
    # Quantification : deux bleus voisins comptent pour un.
    teintes = len({tuple(c // 16 for c in p) for p in rgb.getdata()})
    opaque = sum(1 for p in im.convert("RGBA").getdata() if p[3] > 0)
    part = opaque / (im.width * im.height)
    if part < 0.02:
        return "image vide"
    if teintes <= 2:
        return "aplat uni"
    # Les deux mesures ENSEMBLE, jamais seules : le logo Bayer compte 182
    # teintes, plus que la photo du siege de Lanxess (116). Ce qui les
    # separe, c'est le detourage - un logo garde un pourtour blanc qui
    # devient transparent, une photo occupe tout le carre. Seuils releves
    # sur dix cas de chaque famille (voir la planche de contact).
    if teintes >= 90 and part >= 0.82:
        return f"photo ({teintes} teintes, {part:.0%} plein)"
    return None


def trier():
    """Ecarte ce qui n'est pas un logo, dans logos/_rejetes/."""
    rejet = LOGOS / "_rejetes"
    rejet.mkdir(exist_ok=True)
    gardes, ecartes = [], []
    for s in sujets():
        f = fichier(s["symbole"])
        if not f.exists():
            continue
        souci = _diagnostic(Image.open(f))
        if souci:
            f.replace(rejet / f.name)
            ecartes.append((s["nom"], souci))
        else:
            gardes.append(s["nom"])
    print(f"  {len(gardes)} logos gardes, {len(ecartes)} ecartes\n")
    for nom, souci in sorted(ecartes, key=lambda x: x[1]):
        print(f"  ecarte   {nom:<26} {souci}")
    print(f"\n  Les fichiers ecartes sont dans {rejet.name}/ - a relire,")
    print("  certains sont peut-etre recuperables a la main.")


COTE_MAX = 256


def alleger():
    """Ramène les logos à COTE_MAX de côté.

    Ils sont affichés à 180 px au maximum (filigrane) et 30 px (pastille),
    mais certains fournisseurs renvoient l'image de partage du site en pleine
    résolution : 1024x767 pour 602 Ko chez ASML. Ces octets partent dans git
    ET dans l'image Docker, pour zéro pixel visible de plus.
    """
    gagne = 0
    for s in sujets():
        f = fichier(s["symbole"])
        if not f.exists():
            continue
        im = Image.open(f)
        if max(im.size) <= COTE_MAX:
            continue
        avant = f.stat().st_size
        ratio = COTE_MAX / max(im.size)
        im.convert("RGBA").resize(
            (max(1, int(im.width * ratio)), max(1, int(im.height * ratio))),
            Image.LANCZOS).save(f, optimize=True)
        apres = f.stat().st_size
        gagne += avant - apres
        print(f"  {s['nom']:<24} {im.width}x{im.height} -> {COTE_MAX}px, "
              f"{avant // 1024} Ko -> {apres // 1024} Ko")
    total = sum(fichier(s["symbole"]).stat().st_size
                for s in sujets() if fichier(s["symbole"]).exists())
    print(f"\n  {gagne / 1048576:.1f} Mo economises, {total / 1024:.0f} Ko au total.")


def etat():
    t = table()
    total = len(sujets())
    avec = sum(1 for s in sujets() if fichier(s["symbole"]).exists())
    sans_domaine = [s["symbole"] for s in sujets() if not t.get(s["symbole"])]
    print(f"  {avec}/{total} sujets ont un logo")
    print(f"  {len(sans_domaine)} sans domaine renseigne")
    if sans_domaine:
        print("  " + ", ".join(sans_domaine[:20]) + ("..." if len(sans_domaine) > 20 else ""))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deviner", action="store_true")
    p.add_argument("--telecharger", action="store_true")
    p.add_argument("--planche", action="store_true")
    p.add_argument("--trier", action="store_true")
    p.add_argument("--alleger", action="store_true")
    p.add_argument("--etat", action="store_true")
    a = p.parse_args()
    if a.deviner:
        sys.exit(deviner() or 0)
    if a.telecharger:
        sys.exit(telecharger() or 0)
    if a.trier:
        sys.exit(trier() or 0)
    if a.alleger:
        sys.exit(alleger() or 0)
    if a.planche:
        sys.exit(planche() or 0)
    sys.exit(etat() or 0)
