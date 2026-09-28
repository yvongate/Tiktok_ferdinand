"""Tout ce qui change d'une vidéo à l'autre, en un seul endroit.

Deux vidéos de la chaîne partageaient jusqu'ici la même couleur de
sous-titres, la même lumière, la même voix, la même trajectoire de filigrane
et — pour le format graphique — les mêmes cinq phrases au mot près. Ce module
tire ces réglages au sort.

Trois principes :

  - **Déterministe.** Le tirage dépend du sujet, pas de l'heure. Relancer une
    vidéo après un échec redonne exactement la même ambiance : sans ça, une
    reprise depuis le cache mélangerait des scènes tournées au petit matin
    avec des scènes tournées de nuit. On utilise hashlib et non `hash()`,
    qui change à chaque démarrage de Python (PYTHONHASHSEED).

  - **Borné.** Le hasard ne doit jamais produire quelque chose d'illisible.
    Les sous-titres sont tirés en couleurs claires et saturées, qui passent
    sur n'importe quel fond grâce au contour noir du style ASS ; les courbes
    du graphique restent au-dessus d'un seuil de luminosité, le fond en
    dessous.

  - **Le sens ne se tire pas au sort.** Vert = gain et rouge = perte sont lus
    en un quart de seconde ; les décliner en violet et orange ferait perdre
    cette lecture immédiate. On fait donc varier la NUANCE à l'intérieur de
    chaque famille, jamais la famille elle-même.
"""
import colorsys
import functools
import hashlib
import random


# --- Ambiances Ferdinand -----------------------------------------------
# Ce qui varie ici, c'est la LUMIERE, jamais le medium ni le personnage :
# STYLE_LOCK garde « 3D CGI semi-realiste, qualite cinematique », CHARACTER
# garde le renard au mot pres. Deux videos se distinguent au premier coup
# d'oeil sans cesser d'appartenir au meme univers.
#
# Pour resserrer l'identite visuelle, il suffit de couper cette liste aux
# trois premieres : elles sont volontairement proches les unes des autres.
AMBIANCES = [
    "soft grey overcast morning light, cool diffuse tones, no hard shadows",
    "late afternoon light, warm low sun, long soft shadows",
    "blue evening light outside, warm artificial light from windows and lamps",
    "overcast rainy day, wet reflective asphalt, flat silver light",
    "night scene lit by orange street lamps and shop windows",
]


# --- Charpentes narratives Ferdinand -----------------------------------
# Remplace la seule forme disponible jusqu'ici (sensation -> raison cachee).
# L'accroche (etape 1) et la chute + appel (etapes 5-6) ne bougent pas : ce
# sont le format et la signature de la chaine. Seul le CHEMIN entre les deux
# change.
CHARPENTES = [
    # L'originale, reprise MOT POUR MOT du prompt d'avant : c'est la seule
    # dont le rendu a ete valide a l'ecran, elle ne doit pas deriver.
    ("revelation",
     "2. THE RELATABLE FEELING (1-2 sentences): describe the everyday experience so the "
     "viewer instantly recognizes themselves in it - concrete and specific, but no "
     "character or invented numbers needed here, just a vivid, familiar situation.\n"
     "3. THE HIDDEN REASON (2-4 sentences): reveal the real underlying mechanism - a "
     "psychological bias, a business/pricing strategy, a banking mechanism, or an economic "
     "principle - explained in the simplest possible terms. Use a number ONLY if one "
     "genuinely helps illustrate the mechanism (e.g. a typical price, rate, or percentage) "
     "- never invent a chain of numbers for their own sake."),

    ("contre-pied",
     "2. WHAT EVERYONE BELIEVES (1-2 sentences): state, without irony, the explanation "
     "almost everyone gives for this - the obvious, reasonable-sounding one.\n"
     "3. WHY THAT IS WRONG, AND WHAT IS ACTUALLY HAPPENING (2-4 sentences): dismantle it "
     "in one sentence, then reveal the real mechanism underneath."),

    ("trois-signes",
     "2. THREE CONCRETE SIGNS (3 short sentences, one per sign): three small everyday "
     "situations the viewer has already lived through, listed one after another, without "
     "explaining them yet - let them pile up.\n"
     "3. WHAT THEY HAVE IN COMMON (2-3 sentences): reveal the single mechanism that "
     "produces all three at once."),

    ("chronologie",
     "2. HOW IT STARTS (1-2 sentences): the first month, or the first time it happened - "
     "small enough that nobody reacts.\n"
     "3. WHERE IT ENDS UP (3-4 sentences): walk forward in time in two or three steps "
     "(six months later, two years later), showing the mechanism compounding quietly, "
     "and name it plainly at the end."),
]


# --- Voix ---------------------------------------------------------------
# `audio_profile` est du texte libre decrivant l'intention de jeu : le faire
# varier est sans risque. Le TIMBRE, lui, se choisit par `voice_name`, dont
# les valeurs acceptees sont propres au fournisseur - en inventer ferait
# echouer l'appel TTS et couterait des reprises. VOIX_TIMBRES reste donc vide
# tant qu'on n'a pas valide les noms disponibles cote KIE.AI, un test court
# par nom.
PROFILS = [
    "dramatic {name} narrator",
    "calm, measured {name} narrator, quietly confident",
    "conversational {name} narrator, close to the microphone, like a friend explaining",
]

VOIX_TIMBRES = []  # ex. ["Zephyr", "Puck", "Kore"] une fois validees


# --- Sous-titres --------------------------------------------------------
# Le style ASS pose un contour noir epais (Outline 7), donc n'importe quelle
# couleur CLAIRE passe sur n'importe quel fond. On borne la luminosite par le
# bas et la saturation par le haut : un jaune fluo fatigue, un pastel se perd.
SAT_ACTIVE = (0.55, 0.95)
VAL_ACTIVE = (0.92, 1.00)

# Hauteurs possibles du bloc de sous-titres, pour Ferdinand. En dessous de
# 1050 on entre dans la legende TikTok, au-dessus de 820 on mange l'image.
Y_FERDINAND = (860, 1010)
# Format graphique : la bande libre est entre la carte-titre et le trace.
Y_GRAPHIQUE = (320, 390)


# --- Graphique ----------------------------------------------------------
# Familles de teintes, pas couleurs libres : la lecture « vert = ca monte,
# rouge = ca descend » doit rester instantanee.
TEINTE_GAIN = (0.28, 0.45)      # vert franc -> emeraude -> turquoise
TEINTE_PERTE = (0.96, 1.04)     # framboise -> rouge -> corail (passe par 0)
# La carte-titre est le plus gros aplat de couleur de l'image : c'est elle
# qu'on voit en premier. Une plage trop etroite (bleu -> indigo) donnait deux
# cartes quasi identiques d'une video a l'autre - verifie a l'image.
TEINTE_ACCENT = (0.48, 0.80)    # turquoise -> bleu -> indigo -> violet

# Ligne de reference (la mise de depart). Elle etait tracee en ROUGE, la
# couleur des pertes : des qu'une valeur finissait perdante, les deux courbes
# etaient rouges et on ne distinguait plus ce qu'on avait investi de ce que
# c'etait devenu. Ce n'est ni un gain ni une perte, c'est un repere : teinte
# libre mais tres desaturee, elle ne peut donc jamais etre confondue avec les
# courbes saturees de gain ou de perte.
SAT_REPERE = (0.05, 0.18)
VAL_REPERE = (0.78, 0.92)

REVELATION = (52.0, 68.0)       # duree de montee de la courbe
MAINTIEN = (4.0, 7.0)           # image finale tenue
MEDAILLON = (108, 136)          # diametre du rond Ferdinand


def _graine(texte):
    """Entier stable pour un sujet donne.

    hashlib et non hash() : ce dernier est sale differemment a chaque
    demarrage de Python, si bien qu'une reprise de job aurait retire des
    couleurs et une ambiance differentes de la premiere tentative.
    """
    return int(hashlib.sha256(texte.encode("utf-8")).hexdigest()[:12], 16)


def _paquet(liste, index, sel):
    """Tire dans un paquet battu plutôt qu'à chaque fois dans le sac entier.

    Un tirage indépendant redonne la même charpente d'une vidéo à la suivante
    une fois sur quatre, et la même ambiance une fois sur cinq — ce qui est
    précisément ce qu'on cherche à éviter. Ici, les quatre charpentes sont
    épuisées avant qu'une seule revienne, et l'ordre est rebattu à chaque
    tour, donc deux cycles ne se suivent pas dans le même ordre.

    `index` est le numéro du sujet dans sa liste validée : il donne la
    position dans le paquet sans qu'on ait à retenir quoi que ce soit.
    """
    tour, position = divmod(max(0, index), len(liste))
    return _ordre(tuple(liste), tour, sel)[position]


@functools.lru_cache(maxsize=512)
def _ordre(liste, tour, sel):
    """Ordre du paquet pour un tour donné.

    Le battage seul laisse une couture : le dernier d'un tour peut être le
    premier du suivant, et deux vidéos voisines se ressemblent — le cas le
    plus visible de tous. On interdit donc au nouveau paquet de commencer par
    ce qui vient juste de sortir.
    """
    ordre = list(liste)
    random.Random(_graine(f"{sel}#{tour}")).shuffle(ordre)
    if tour > 0 and len(ordre) > 1:
        precedent = _ordre(liste, tour - 1, sel)[-1]
        if ordre[0] == precedent:
            ordre[0], ordre[1] = ordre[1], ordre[0]
    return tuple(ordre)


def _rgb(rng, teinte, sat, val):
    h = rng.uniform(*teinte) % 1.0
    r, v, b = colorsys.hsv_to_rgb(h, rng.uniform(*sat), rng.uniform(*val))
    return int(r * 255), int(v * 255), int(b * 255)


def _ass(rgb):
    """Couleur ASS : &HBBGGRR&, l'inverse de l'ordre web."""
    r, v, b = rgb
    return f"&H{b:02X}{v:02X}{r:02X}&"


class Variation:
    """Reglages tires pour UNE video. Deterministe pour un sujet donne."""

    def __init__(self, sujet, index=0, lang="de"):
        self.sujet = sujet
        self.index = index
        rng = random.Random(_graine(sujet))
        self.rng = rng

        # --- sous-titres : un mot actif colore, les autres presque blancs ---
        self.couleur_active = _ass(_rgb(rng, (0.0, 1.0), SAT_ACTIVE, VAL_ACTIVE))
        # Inactif : blanc legerement teinte, jamais colore - sinon les deux
        # couleurs se disputent l'attention et on ne voit plus quel mot est lu.
        self.couleur_inactive = _ass(_rgb(rng, (0.0, 1.0), (0.0, 0.10), (0.97, 1.0)))
        self.y_ferdinand = rng.randint(*Y_FERDINAND)
        self.y_graphique = rng.randint(*Y_GRAPHIQUE)

        # --- voix ---
        nom = {"de": "German", "fr": "French", "en": "English"}.get(lang, "English")
        self.profil_voix = _paquet(PROFILS, index, "voix").format(name=nom)
        self.timbre = _paquet(VOIX_TIMBRES, index, "timbre") if VOIX_TIMBRES else "Zephyr"

        # --- Ferdinand ---
        self.ambiance = _paquet(AMBIANCES, index, "ambiance")
        self.charpente_nom, self.charpente = _paquet(CHARPENTES, index, "charpente")

        # --- filigrane : meme contrainte que l'original (moitie haute, hors
        # colonne des boutons TikTok), trajectoire differente ---
        self.waypoints = [(rng.randint(180, 560), rng.randint(170, 700)) for _ in range(6)]

        # --- bruitages ---
        self.graine_sfx = rng.randrange(1 << 30)

        # --- graphique ---
        self.gain = _rgb(rng, TEINTE_GAIN, (0.62, 0.88), (0.78, 0.95))
        self.perte = _rgb(rng, TEINTE_PERTE, (0.62, 0.90), (0.80, 0.96))
        self.accent = _rgb(rng, TEINTE_ACCENT, (0.55, 0.85), (0.80, 0.98))
        self.repere = _rgb(rng, (0.0, 1.0), SAT_REPERE, VAL_REPERE)
        # Fond : toujours tres sombre, teinte libre. Au-dessus de 0.10 de
        # valeur, les courbes claires perdent leur contraste.
        self.fond = _rgb(rng, (0.0, 1.0), (0.25, 0.70), (0.022, 0.055))
        self.grille = tuple(min(255, c + rng.randint(16, 30)) for c in self.fond)
        self.revelation = round(rng.uniform(*REVELATION), 1)
        self.maintien = round(rng.uniform(*MAINTIEN), 1)
        self.medaillon = rng.randint(*MEDAILLON)

    def resume(self):
        """Ligne de journal : sans elle, impossible de savoir apres coup
        pourquoi deux videos ne se ressemblent pas."""
        return (f"charpente={self.charpente_nom} ambiance={self.ambiance.split(',')[0]!r} "
                f"voix={self.profil_voix.split(',')[0]!r} "
                f"sous-titres={self.couleur_active} y={self.y_ferdinand}")

    def resume_graphique(self):
        return (f"gain={self.gain} perte={self.perte} fond={self.fond} "
                f"montee={self.revelation}s maintien={self.maintien}s "
                f"medaillon={self.medaillon}px voix={self.profil_voix.split(',')[0]!r}")


def pour(sujet, index=0, lang="de"):
    """Réglages de cette vidéo.

    `index` est le rang du sujet dans sa liste validée ; il sert à tirer dans
    un paquet battu plutôt qu'au hasard, pour que deux vidéos publiées à la
    suite ne partagent ni charpente, ni ambiance, ni voix.
    """
    return Variation(sujet, index, lang)
