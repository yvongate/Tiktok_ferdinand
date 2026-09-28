"""Filigrane mobile incruste sur la video finale.

Un filigrane n'empeche pas le vol : il se recadre, se floute ou se masque.
Ce qu'il apporte, c'est l'ATTRIBUTION - celui qui voit une video repostee
peut remonter au compte d'origine.

D'ou le choix d'une derive lente plutot qu'un coin fixe : un texte immobile
se recadre d'un geste, tandis que celui-ci traverse 500 px verticalement, ce
qui oblige a masquer la moitie de l'image pour s'en debarrasser.

Desactive par defaut : sans WATERMARK dans l'environnement, rien n'est
incruste. Le nom de compte se renseigne cote hebergeur, sans toucher au code
ni reconstruire l'image Docker.
"""
import os
from pathlib import Path

import subtitles

ENV_VAR = "WATERMARK"

FONT_SIZE = 34
# Opacite : 00 = opaque, FF = invisible. A8 laisse le texte lisible grace au
# contour noir sans jamais disputer l'attention a la narration.
ALPHA = "A8"

# Parcours dans la moitie haute. Deux zones sont interdites :
#   - x > 600  : colonne des boutons TikTok (like, commentaire, partage)
#   - y > 900  : legende TikTok, et nos propres sous-titres a y=980
WAYPOINTS = [(200, 180), (520, 300), (240, 560), (540, 680), (200, 320), (420, 180)]


def configured(override=None):
    """Texte du filigrane, ou chaine vide si aucun n'est configure."""
    if override:
        return override.strip()
    return (os.environ.get(ENV_VAR) or "").strip()


def _timestamp(seconds):
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text):
    """Neutralise ce que libass interpreterait comme des balises."""
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def build_ass(duration, out_path, override=None, waypoints=None):
    """Ecrit le fichier ASS du filigrane pour une video de `duration`.

    `waypoints` remplace le parcours par defaut. Il etait fige, donc le
    filigrane suivait exactement le meme chemin sur toutes les videos de la
    chaine - un motif repere bien plus vite qu'une couleur.

    Renvoie le nombre de segments ecrits, 0 si aucun filigrane n'est configure
    ou si la duree est inexploitable.
    """
    points = waypoints or WAYPOINTS
    text = _escape(configured(override))
    if not text or duration <= 0:
        return 0

    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.601\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: WM,{subtitles.FONT_NAME},{FONT_SIZE},&H{ALPHA}FFFFFF,"
        f"&H000000FF,&H{ALPHA}101010,&H00000000,-1,0,0,0,100,100,0,0,1,3,2,5,"
        "40,40,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    # Une balise \move est relative au debut de SA ligne : le parcours se
    # decoupe donc en autant de lignes que de segments.
    segments = len(points) - 1
    span = duration / segments
    lines = []
    for i in range(segments):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        start, end = i * span, min(duration, (i + 1) * span)
        ms = int(span * 1000)
        lines.append(
            f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},WM,,0,0,0,,"
            f"{{\\move({x1},{y1},{x2},{y2},0,{ms})}}{text}"
        )

    Path(out_path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)
