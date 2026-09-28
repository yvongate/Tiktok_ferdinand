"""Rendu du graphique boursier animé, image par image.

Tracé en PIL, sans matplotlib : une polyligne ne justifie pas une
bibliothèque scientifique dans l'image Docker.

Trois choix qui structurent le rendu :
  - échelle ADAPTATIVE, calculée sur la portion déjà révélée. La figer sur
    toute la période montrerait le sommet dès la première image et
    supprimerait le suspense ;
  - la courbe est LISSÉE pour le tracé mais les CHIFFRES restent bruts :
    on embellit la ligne, jamais le résultat ;
  - un seul point par colonne de pixels. La zone de tracé fait ~470 px, donc
    tracer 5 000 points revenait à empiler dix points invisibles par pixel.
"""
import datetime
import http.client
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICI = Path(__file__).parent
POLICE = ICI / "fonts" / "Montserrat-ExtraBold.ttf"

L, H = 720, 1280
GX0, GX1 = 96, L - 150          # marge droite : place pour les étiquettes
GY0, GY1 = 430, 1010

FOND = (6, 7, 12)
GRILLE = (26, 30, 42)
VERT = (46, 229, 133)
ROUGE = (235, 60, 70)
BLANC = (246, 246, 250)
BLEU = (58, 140, 255)
GRIS = (150, 156, 172)

LISSAGE = 90                    # moyenne mobile, en jours de bourse
API = "https://query1.finance.yahoo.com/v8/finance/chart"


def _http(url, essais=4):
    """Appel Yahoo avec reprises.

    Il n'y en avait aucune, alors que generate.py retente tous ses appels.
    Yahoo limite agressivement les adresses de centres de donnees - or Render
    en partage une : un 429 passager tuait le job avec un traceback brut, que
    le backend ne savait classer qu'en « cause inconnue ». Les messages
    imprimes ici reprennent la grammaire de generate.py, pour que le meme
    analyseur les reconnaisse comme incidents.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for essai in range(1, essais + 1):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")[:200]
            print(f"  HTTP {e.code}: {corps}")
            # 404/422 : le symbole est faux, retenter n'y changera rien.
            if e.code not in (429, 500, 502, 503, 504):
                raise ValueError(f"cours indisponible (HTTP {e.code})") from None
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException, json.JSONDecodeError) as e:
            print(f"  Erreur reseau ({type(e).__name__}): {e}")
        if essai < essais:
            print(f"  (retry {essai}/{essais})")
            time.sleep(5 * essai)
    raise ValueError("donnees boursieres injoignables apres plusieurs tentatives")


def _points(symbole, annees, pas="1d"):
    d = _http(f"{API}/{symbole}?range={annees}y&interval={pas}")
    try:
        res = d["chart"]["result"][0]
        pts = [(t, c) for t, c in
               zip(res["timestamp"], res["indicators"]["adjclose"][0]["adjclose"]) if c]
        devise = res["meta"]["currency"]
    except (KeyError, IndexError, TypeError):
        # Reponse bien formee mais vide : valeur retiree de la cote, symbole
        # renomme... `min()` plus bas levait alors un « arg is an empty
        # sequence » qui ne designait rien.
        raise ValueError(f"serie vide pour {symbole}") from None
    if len(pts) < 2:
        raise ValueError(f"serie vide pour {symbole} ({len(pts)} point(s))")
    return pts, devise


def _lisser(valeurs, fenetre):
    if fenetre <= 1:
        return valeurs
    demi = fenetre // 2
    return [
        sum(valeurs[max(0, i - demi):min(len(valeurs), i + demi + 1)])
        / len(valeurs[max(0, i - demi):min(len(valeurs), i + demi + 1)])
        for i in range(len(valeurs))
    ]


def charger(symbole, annees, mise=100):
    """[(horodatage, valeur_lissee, valeur_reelle)] pour la période demandée.

    Les cours en devise étrangère sont convertis AU TAUX DE CHAQUE MOIS :
    l'évolution de la devise fait partie du rendement réellement subi par un
    investisseur en euros. Convertir au taux du jour afficherait un résultat
    que personne n'a touché.
    """
    pts, devise = _points(symbole, annees)
    if min(c for _, c in pts) <= 0:
        # Sur les historiques longs de valeurs à gros dividendes, le cours
        # « ajusté » de Yahoo finit par passer sous zéro. Série inexploitable.
        raise ValueError(f"serie invalide pour {symbole} (cours negatif)")

    if devise != "EUR":
        fx, _ = _points(f"EUR{devise}=X", annees, pas="1mo")
        par_mois = {
            datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m"): v
            for t, v in fx
        }
        convertis = []
        for t, c in pts:
            taux = par_mois.get(datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m"))
            if taux:
                convertis.append((t, c / taux))
        if not convertis:
            raise ValueError(f"aucun taux de change pour {devise}")
        pts = convertis

    base = pts[0][1]
    brut = [mise * c / base for _, c in pts]
    return list(zip([t for t, _ in pts], _lisser(brut, LISSAGE), brut))


def medaillon(source, taille=120, debut=16.2, secondes=3.0, fps=24):
    """Images circulaires de Ferdinand, découpées dans une vidéo existante.

    Aucune génération payante : les vidéos déjà produites le contiennent en
    mouvement (respiration, clignements).
    """
    import subprocess
    dossier = ICI / "_medaillon"
    if not any(dossier.glob("f_*.png")):
        dossier.mkdir(exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", str(debut), "-t", str(secondes),
             "-i", str(source), "-vf", f"crop=350:350:10:125,fps={fps}",
             str(dossier / "f_%03d.png")], check=False)
    masque = Image.new("L", (taille, taille), 0)
    ImageDraw.Draw(masque).ellipse((0, 0, taille - 1, taille - 1), fill=255)
    images = []
    for f in sorted(dossier.glob("f_*.png")):
        im = Image.open(f).convert("RGB").resize((taille, taille), Image.LANCZOS)
        rond = Image.new("RGBA", (taille, taille))
        rond.paste(im, (0, 0), masque)
        images.append(rond)
    return images


LOGOS = ICI / "logos"


def logo(symbole):
    """Logo de l'entreprise, ou None.

    Lu dans python/logos/<SYMBOLE>.png, les points du symbole remplacés par
    des tirets bas (BAYN.DE -> BAYN_DE.png). Rien n'est téléchargé : un logo
    est une marque déposée, il n'a pas à arriver dans la vidéo par une source
    que personne n'a regardée. Absent, le graphique se dessine comme avant.
    """
    # Le nom vient du fichier de sujets ; un symbole contenant « / » ou « .. »
    # sortirait du dossier. Il est relu a la main et versionne, donc le risque
    # est theorique - mais la garde coute une ligne.
    nom = symbole.replace(".", "_")
    if "/" in nom or "\\" in nom or nom.startswith("."):
        return None
    chemin = LOGOS / (nom + ".png")
    if not chemin.exists():
        return None
    try:
        return Image.open(chemin).convert("RGBA")
    except OSError:
        return None


def prepare_filigrane(source, largeur=180, alpha=38):
    """Voile estompé du logo, et sa position. Calculé UNE fois.

    Dessiné sous la courbe et très transparent : il situe l'entreprise sans
    disputer la lisibilité au graphique, qui reste le sujet de la vidéo.

    180 px et non 370 : la source fait 128 px de côté chez la plupart des
    fournisseurs de logos, et l'agrandir presque trois fois donnait un bord
    crénelé, visible à l'image.

    Le redimensionnement et la couche alpha étaient refaits à CHAQUE image,
    alors que le résultat ne change jamais : 3,4 ms par image mesurées, soit
    une quinzaine de secondes par vidéo sur le demi-CPU de Render. Le
    médaillon de Ferdinand, lui, était déjà pré-calculé.
    """
    ratio = largeur / source.width
    petit = source.resize((largeur, max(1, int(source.height * ratio))), Image.LANCZOS)
    voile = petit.copy()
    voile.putalpha(petit.getchannel("A").point(lambda a: int(a * alpha / 255)))
    return voile, ((GX0 + GX1) // 2 - voile.width // 2,
                   (GY0 + GY1) // 2 - voile.height // 2)


def prepare_pastille(source, diametre=30):
    """Logo en pastille ronde, pour la pointe de la courbe. Calculé une fois."""
    petit = source.resize((diametre, diametre), Image.LANCZOS)
    masque = Image.new("L", (diametre, diametre), 0)
    ImageDraw.Draw(masque).ellipse((0, 0, diametre - 1, diametre - 1), fill=255)
    rond = Image.new("RGBA", (diametre, diametre))
    rond.paste(petit, (0, 0), masque)
    return rond


def _euro(v, centimes=False):
    s = f"{v:,.2f}" if centimes else f"{v:,.0f}"
    return s.replace(",", " ").replace(".", ",") + " €"


_ROTATIONS = {}


def _incline(txt, police, couleur, angle=35):
    # Une vingtaine d'années distinctes, mais elles étaient repivotées en
    # bicubique à chaque image : 12 000 rotations sur une vidéo.
    cle = (txt, angle, couleur)
    if cle not in _ROTATIONS:
        tmp = Image.new("RGBA", (200, 48), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((0, 8), txt, font=police, fill=couleur)
        r = tmp.rotate(angle, expand=True, resample=Image.BICUBIC)
        _ROTATIONS[cle] = r.crop(r.getbbox())
    return _ROTATIONS[cle]


def _halo(d, pts, couleur, largeur=4, fond=FOND):
    for w, melange in ((largeur + 7, 0.14), (largeur + 3, 0.3), (largeur, 1.0)):
        c = tuple(int(fond[i] + (couleur[i] - fond[i]) * melange) for i in range(3))
        d.line(pts, fill=c, width=w, joint="curve")


class Rendu:
    """Dessine une image de l'animation. Les polices et le médaillon sont
    chargés une fois pour toutes, pas à chaque image."""

    def __init__(self, donnees, titre, annee_debut, mise=100, badges=None,
                 palette=None, titre_lignes=None, logo_img=None):
        self.donnees = donnees
        self.titre = titre
        self.annee_debut = annee_debut
        self.mise = mise
        # Carte-titre : deux lignes, formulees en dur jusqu'ici, donc
        # identiques au mot pres sur les 95 sujets. Le marqueur « POV: » est
        # le format et ne bouge pas ; la formulation qui suit, oui.
        self.titre_lignes = titre_lignes or [
            f"POV: Du hast {annee_debut}",
            f"{mise} € in {titre} investiert",
        ]
        self.badges = badges or []
        # Palette : les couleurs etaient des constantes de module, donc
        # identiques sur les 95 sujets. `palette` les remplace ; sans elle on
        # retombe exactement sur le rendu d'origine.
        p = palette or {}
        self.fond = p.get("fond", FOND)
        self.grille = p.get("grille", GRILLE)
        self.gain = p.get("gain", VERT)
        self.perte = p.get("perte", ROUGE)
        self.accent = p.get("accent", BLEU)
        # Couleur de la ligne « Investi ». Distincte de gain ET de perte : la
        # mise de depart est un repere, pas un resultat.
        self.repere = p.get("repere", GRIS)
        # Voile et pastille prets a coller : ils ne dependent que du logo,
        # pas de l'image en cours.
        self.voile, self.voile_xy = (prepare_filigrane(logo_img) if logo_img
                                     else (None, (0, 0)))
        self.pastille = prepare_pastille(logo_img) if logo_img else None
        self._polices = {}
        self.f_titre = ImageFont.truetype(str(POLICE), 30)
        self.f_axe = ImageFont.truetype(str(POLICE), 19)
        self.f_lab = ImageFont.truetype(str(POLICE), 21)
        self.f_val = ImageFont.truetype(str(POLICE), 19)
        self.f_bas = ImageFont.truetype(str(POLICE), 34)

    # Largeur utile de la carte-titre : sa boite moins une marge de chaque
    # cote, pour que le texte ne touche pas le bord arrondi.
    LARGEUR_TITRE = (L - 78) - 78 - 2 * 18

    def _police_titre(self, d, ligne):
        """Police reduite juste ce qu'il faut pour que la ligne tienne.

        Les tailles sont mises en cache : sans ca, on mesurerait et
        rechargerait la police a chaque image, soit 1 500 fois par video.
        """
        if ligne not in self._polices:
            taille = 30
            while taille > 19 and d.textlength(
                    ligne, font=ImageFont.truetype(str(POLICE), taille)) > self.LARGEUR_TITRE:
                taille -= 1
            self._polices[ligne] = ImageFont.truetype(str(POLICE), taille)
        return self._polices[ligne]

    def image(self, avancement, frame=0):
        n = max(2, int(len(self.donnees) * avancement))
        vus = self.donnees[:n]
        img = Image.new("RGB", (L, H), self.fond)
        # Avant la grille et la courbe : le logo est un fond, pas un calque.
        if self.voile is not None:
            img.paste(self.voile, self.voile_xy, self.voile)
        d = ImageDraw.Draw(img)

        vals = [v for _, v, _ in vus] + [self.mise]
        vmin, vmax = min(vals), max(vals)
        if vmax - vmin < 1e-6:
            vmin, vmax = vmin * 0.9, vmax * 1.1
        marge = (vmax - vmin) * 0.12
        vmin, vmax = vmin - marge, vmax + marge

        brut = (vmax - vmin) / 5
        mag = 10 ** int(math.floor(math.log10(brut)))
        pas = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= brut)
        premier = math.floor(vmin / pas) * pas

        ypix = lambda v: GY1 - (v - vmin) / (vmax - vmin) * (GY1 - GY0)
        xpix = lambda i: GX0 + (i / max(1, n - 1)) * (GX1 - GX0)

        k = 0
        while premier + k * pas <= vmax:
            v = premier + k * pas
            k += 1
            if v < vmin:
                continue
            y = ypix(v)
            d.line([(GX0, y), (GX1 + 6, y)], fill=self.grille, width=1)
            lab = (f"{v:,.0f}" if pas >= 1 else f"{v:,.1f}").replace(",", " ")
            d.text((GX0 - 12 - d.textlength(lab, font=self.f_axe), y - 10), lab,
                   font=self.f_axe, fill=GRIS)
        d.line([(GX0, GY0 - 20), (GX0, GY1 + 8)], fill=(70, 76, 92), width=2)
        d.line([(GX0, GY1 + 8), (GX1 + 10, GY1 + 8)], fill=(70, 76, 92), width=2)
        d.text((GX0 - 34, GY0 - 58), "€", font=self.f_lab, fill=BLANC)

        for k in range(8):
            i = int(k * (n - 1) / 7)
            an = datetime.datetime.fromtimestamp(
                vus[i][0], datetime.timezone.utc).strftime("%Y")
            rot = _incline(an, self.f_axe, GRIS)
            img.paste(rot, (int(xpix(i)) - 34, GY1 + 16), rot)

        entier = [(xpix(i), ypix(v)) for i, (_, v, _) in enumerate(vus)]
        courbe, colonne = [], None
        for px, py in entier:
            if int(px) != colonne:
                courbe.append((px, py))
                colonne = int(px)
        if courbe[-1] != entier[-1]:
            courbe.append(entier[-1])

        actuel = vus[-1][2]
        couleur = self.gain if actuel >= self.mise else self.perte
        _halo(d, courbe, couleur, fond=self.fond)
        y0 = ypix(self.mise)
        _halo(d, [(GX0, y0), (xpix(n - 1), y0)], self.repere, largeur=3, fond=self.fond)

        for (px, py), nom, val, c in (
            ((xpix(n - 1), y0), "Investi", self.mise, self.repere),
            (courbe[-1], self.titre, actuel, couleur),
        ):
            d.ellipse((px - 11, py - 11, px + 11, py + 11), fill=c,
                      outline=BLANC, width=2)
            # « Commerzbank » debordait de 70px a droite et sortait coupe en
            # plein milieu du mot : la marge de GX1 a ete calculee pour
            # « Investi », pas pour les noms longs. On bascule alors
            # l'etiquette A GAUCHE du point - la simple rentrer dans le cadre
            # la ferait chevaucher le marqueur.
            montant = _euro(val, True)
            large = max(d.textlength(nom, font=self.f_lab),
                        d.textlength(montant, font=self.f_val))
            x = px + 20 if px + 20 + large <= L - 12 else max(8, px - 20 - large)
            d.text((x, py - 24), nom, font=self.f_lab, fill=c)
            d.text((x, py + 2), montant, font=self.f_val, fill=BLANC)
            # Le point de l'entreprise porte son logo ; celui de la mise reste
            # une pastille de couleur, il ne represente aucune societe.
            if self.pastille is not None and nom == self.titre:
                r = self.pastille.width // 2
                img.paste(self.pastille, (int(px) - r, int(py) - r), self.pastille)

        d.rounded_rectangle((78, 150, L - 78, 262), radius=18, fill=self.accent)
        for i, ligne in enumerate(self.titre_lignes):
            # La carte-titre etait dessinee sans jamais verifier que le texte y
            # tenait : « 100 € in Commerzbank investiert » debordait jusqu'au
            # bord de l'image. On reduit la police plutot que de couper le mot.
            police = self._police_titre(d, ligne)
            d.text(((L - d.textlength(ligne, font=police)) / 2, 166 + i * 42),
                   ligne, font=police, fill=BLANC)

        ecart = actuel - self.mise
        txt = ("Gewinn : " if ecart >= 0 else "Verlust : ") + _euro(abs(ecart), True)
        d.text(((L - d.textlength(txt, font=self.f_bas)) / 2, 1175), txt,
               font=self.f_bas, fill=self.gain if ecart >= 0 else self.perte)

        if self.badges:
            # Lecture en aller-retour : sans ça, la boucle saute visiblement
            # toutes les trois secondes.
            nb = len(self.badges)
            cycle = max(1, 2 * nb - 2)
            k = frame % cycle
            b = self.badges[k if k < nb else cycle - k]
            pos = (18, 1128)
            anneau = Image.new("RGBA", (b.size[0] + 8, b.size[0] + 8), (0, 0, 0, 0))
            ImageDraw.Draw(anneau).ellipse(
                (0, 0, b.size[0] + 7, b.size[0] + 7), fill=(246, 246, 250, 225))
            img.paste(anneau, (pos[0] - 4, pos[1] - 4), anneau)
            img.paste(b, pos, b)

        return img
