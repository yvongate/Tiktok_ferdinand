"""Sous-titres animes incrustes, facon CapCut.

Fenetre glissante de trois mots : le mot prononce est en jaune et legerement
grossi, les deux autres restent lisibles mais estompes. On garde ainsi le fil
de la phrase tout en suivant la voix, contrairement a un mot isole a l'ecran.

Le minutage est DEDUIT, pas mesure : le TTS ne renvoie aucun timestamp par mot
(verifie sur Gemini). On repartit donc la duree mesuree de chaque scene sur ses
mots. L'architecture scene par scene rend l'approximation acceptable : on
repartit dans un bloc de 4 a 8 secondes, jamais sur la minute entiere.
"""
import re
from pathlib import Path

FONT_NAME = "Montserrat ExtraBold"
FONTS_DIR = Path(__file__).parent / "fonts"

# Les couleurs ASS s'ecrivent &HBBGGRR& (bleu-vert-rouge, a l'envers du web).
COLOR_ACTIVE = "&H00E5FF&"  # jaune
COLOR_IDLE = "&HFFFFFF&"  # blanc

_TAG = re.compile(r"\[[^\]]*\]")
_VOWELS = re.compile(r"[aeiouyàâäéèêëîïôöùûüÿ]+", re.IGNORECASE)

WINDOW = 3
FONT_SIZE = 62
MIN_FONT_SIZE = 34

# Largeur utile : 720px de cadre moins les marges laterales du style (70+70).
USABLE_WIDTH = 580

# Largeur moyenne d'un caractere, en fraction de la taille de police. Mesuree
# sur le rendu reel de Montserrat ExtraBold en capitales a 62px : M = 0.60,
# A = 0.51, I = 0.21. Sert a PREVOIR un debordement sans rendre l'image.
_CHAR_WIDTH = {" ": 0.26, "I": 0.24, "J": 0.36, "L": 0.42, "T": 0.45, "F": 0.44,
               "M": 0.61, "W": 0.66, "O": 0.58, "Q": 0.58, "G": 0.57, "D": 0.56}
_DEFAULT_CHAR_WIDTH = 0.51


def _estimated_width(text, size):
    return size * sum(_CHAR_WIDTH.get(c, _DEFAULT_CHAR_WIDTH) for c in text)


def _fit_size(text, scale=1.0):
    """Taille de police pour que `text` tienne dans le cadre.

    Indispensable en allemand : un mot compose comme
    "Krankenversicherungsbeitraege" (29 lettres) mesure 720px a la taille
    nominale et se retrouve coupe aux deux bords (debordement constate sur
    rendu reel, pas estime). Francais et anglais n'atteignent quasiment jamais
    ce seuil, donc la taille nominale y reste inchangee.

    `scale` tient compte d'un agrandissement applique par ailleurs (le rebond
    du mot actif a 110%).
    """
    width = _estimated_width(text, FONT_SIZE) * scale
    if width <= USABLE_WIDTH:
        return FONT_SIZE
    return max(MIN_FONT_SIZE, int(FONT_SIZE * USABLE_WIDTH / width))


def _weights(words):
    """Poids de chaque mot dans la duree de sa scene.

    Le nombre de voyelles approxime les syllabes ; une ponctuation forte ajoute
    une pause. C'est la ou une repartition strictement lineaire derape le plus,
    parce que la voix marque un silence que le texte ne signale pas autrement.
    """
    out = []
    for w in words:
        weight = max(1, len(_VOWELS.findall(w))) + 0.35
        if w.endswith((".", "!", "?", "…")):
            weight += 1.1
        elif w.endswith((",", ";", ":")):
            weight += 0.5
        out.append(weight)
    return out


def _timestamp(seconds):
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text):
    """Neutralise ce que libass interpreterait comme des balises."""
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{FONT_NAME},{FONT_SIZE},{COLOR_IDLE},&H000000FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _window_for(words, i):
    """Fenetre de mots a afficher autour du mot actif, et taille de police.

    On retrecit la FENETRE avant de retrecir la POLICE : reduire d'abord la
    taille donnait un texte deux fois plus petit qui passait quand meme a la
    ligne. Mieux vaut montrer moins de contexte en gros caracteres que trois
    mots illisibles.

    La police n'est reduite qu'en dernier recours, quand un mot seul deborde -
    cas propre a l'allemand et a ses mots composes.
    """
    for width in range(WINDOW, 0, -1):
        low = max(0, i - (width - 1) // 2)
        high = min(len(words), low + width)
        low = max(0, high - width)
        shown = [_escape(w.upper()) for w in words[low:high]]
        active = _escape(words[i].upper())
        # Deux contraintes : la fenetre entiere doit tenir, et le mot actif
        # aussi pendant son rebond a 110% - sinon il deborde en pleine
        # animation alors que la ligne au repos tenait tout juste.
        size = min(_fit_size(" ".join(shown)), _fit_size(active, scale=1.10))
        if size == FONT_SIZE or width == 1:
            return low, high, size
    return i, i + 1, FONT_SIZE  # inatteignable, garde-fou


def word_timeline(segments):
    """Frise des mots sur la duree totale du montage.

    segments : liste de (texte_parle, duree_mesuree_de_la_voix), dans l'ordre
    exact du montage - les scenes ratees ne doivent PAS y figurer, sinon tout
    ce qui suit est decale.

    Renvoie [(scene, index_du_mot, mot, debut, fin, mots_de_la_scene)].

    Fonction PARTAGEE avec le module des bruitages : les deux doivent poser
    leurs evenements sur exactement la meme frise, sinon un bruitage cale sur
    un mot ne tombe plus sur le sous-titre correspondant.
    """
    out = []
    clock = 0.0
    for scene, (text, duration) in enumerate(segments):
        # Les balises de jeu ([curious], [whispers]) pilotent la diction, elles
        # ne sont pas prononcees : elles n'ont rien a faire dans la frise.
        words = _TAG.sub("", text or "").split()
        if not words or duration <= 0:
            clock += max(0.0, duration)
            continue
        weights = _weights(words)
        total = sum(weights)
        cursor = clock
        for i, (word, weight) in enumerate(zip(words, weights)):
            span = duration * weight / total
            out.append((scene, i, word, cursor, cursor + span, words))
            cursor += span
        clock += duration
    return out


def build_ass(segments, out_path):
    """Ecrit un fichier .ass pour la suite de scenes donnee.

    Renvoie le nombre de mots sous-titres (0 = rien a incruster).
    """
    lines = []

    for _scene, i, _word, start, end, words in word_timeline(segments):
        low, high, size = _window_for(words, i)
        shown_words = [_escape(words[j].upper()) for j in range(low, high)]

        parts = []
        for j in range(low, high):
            shown = shown_words[j - low]
            if j == i:
                parts.append(
                    f"{{\\1c{COLOR_ACTIVE}\\fscx110\\fscy110"
                    f"\\t(0,90,0.5,\\fscx100\\fscy100)}}{shown}{{\\r}}"
                )
            else:
                parts.append(f"{{\\alpha&H60&}}{shown}{{\\r}}")

        override = "" if size == FONT_SIZE else f"\\fs{size}"
        lines.append(
            f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Pop,,0,0,0,,"
            f"{{\\pos(360,980){override}}}{' '.join(parts)}"
        )

    if not lines:
        return 0

    Path(out_path).write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def ass_filter(ass_path):
    """Valeur de -vf pour incruster ce fichier.

    Les deux-points et les antislashs d'un chemin Windows casseraient la
    syntaxe des filtres ffmpeg : on passe donc par un chemin relatif au
    dossier de travail, echappe.
    """
    path = str(ass_path).replace("\\", "/").replace(":", "\\:")
    fonts = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
    return f"ass=f='{path}':fontsdir='{fonts}'"
