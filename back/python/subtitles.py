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
Style: Pop,{FONT_NAME},62,{COLOR_IDLE},&H000000FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(segments, out_path):
    """Ecrit un fichier .ass pour la suite de scenes donnee.

    segments : liste de (texte_parle, duree_mesuree_de_la_voix), dans l'ordre
    exact du montage - les scenes ratees ne doivent PAS y figurer, sinon tous
    les sous-titres suivants sont decales.

    Renvoie le nombre de mots sous-titres (0 = rien a incruster).
    """
    lines = []
    clock = 0.0

    for text, duration in segments:
        # Les balises de jeu ([curious], [whispers]) pilotent la diction, elles
        # ne sont pas prononcees : elles n'ont rien a faire a l'ecran.
        words = _TAG.sub("", text or "").split()
        if not words or duration <= 0:
            clock += max(0.0, duration)
            continue

        weights = _weights(words)
        total = sum(weights)
        cursor = clock

        for i, (word, weight) in enumerate(zip(words, weights)):
            span = duration * weight / total
            start, end = cursor, cursor + span
            cursor = end

            # Fenetre centree sur le mot actif, recadree aux bords de la phrase.
            low = max(0, i - 1)
            high = min(len(words), low + WINDOW)
            low = max(0, high - WINDOW)

            parts = []
            for j in range(low, high):
                shown = _escape(words[j].upper())
                if j == i:
                    parts.append(
                        f"{{\\1c{COLOR_ACTIVE}\\fscx110\\fscy110"
                        f"\\t(0,90,0.5,\\fscx100\\fscy100)}}{shown}{{\\r}}"
                    )
                else:
                    parts.append(f"{{\\alpha&H60&}}{shown}{{\\r}}")

            lines.append(
                f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Pop,,0,0,0,,"
                f"{{\\pos(360,980)}}{' '.join(parts)}"
            )

        clock += duration

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
