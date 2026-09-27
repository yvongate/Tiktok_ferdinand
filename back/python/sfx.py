"""Bruitages : choisis par le modele au decoupage, poses au montage.

Le choix a lieu a l'etape 3 (decoupage en scenes), ou le modele remplit deja
un JSON : un champ de plus ne coute aucun appel API supplementaire. Mais a ce
moment la voix n'existe pas encore, donc aucune duree n'est connue et aucun
horodatage n'est calculable. Le modele ne designe donc qu'un MOT DECLENCHEUR.

La resolution en secondes a lieu a l'etape 5, une fois chaque voix mesuree,
via la frise partagee avec les sous-titres (subtitles.word_timeline) - un
bruitage cale sur un mot tombe ainsi exactement sur son sous-titre.
"""
import json
import random
import subprocess
import unicodedata
from pathlib import Path

import subtitles

SFX_DIR = Path(__file__).parent / "sfx"
MANIFEST = SFX_DIR / "SOURCES.json"

# Gain par categorie, fixe ICI et jamais par le modele : il decide quoi et ou,
# le niveau reste une question d'ingenierie. Les ambiances sont tres basses,
# elles doivent rester sous la narration sans jamais la disputer.
GAIN = {
    "whoosh": 0.30, "swoosh": 0.28, "reverse": 0.26, "impact": 0.26,
    "boom": 0.30, "riser": 0.16, "glitch": 0.26, "subdrop": 0.30,
    "cash": 0.34, "coins": 0.30, "money": 0.30, "swipe": 0.28,
    "paper": 0.30, "pageturn": 0.28, "keyboard": 0.24, "printer": 0.24,
    "door": 0.26, "clock": 0.26, "notification": 0.28, "vibrate": 0.26,
    "click": 0.24, "ding": 0.28, "error": 0.28, "pop": 0.24,
    "heartbeat": 0.26, "breath": 0.22, "crowd": 0.22, "applause": 0.24,
    "office": 0.14, "city": 0.14,
}
DEFAULT_GAIN = 0.25

# La plupart des bruitages ont une attaque : les poser legerement AVANT le mot
# fait tomber leur pic sur la syllabe, pas apres.
LEAD = 0.08

# Garde-fou de densite : filet contre l'emballement, pas regle editoriale.
# Une scene dure 3,5 a 8,5s, donc un bruitage par scene represente au plus
# ~3 par tranche de 10s - le plafond est a 4 pour ne jamais ecarter un choix
# legitime, tout en bloquant un vrai deraillement.
MAX_PER_10S = 4


def _normalize(word):
    """Sans accents, sans ponctuation, en minuscules.

    Indispensable pour comparer un mot du script au mot rendu par le modele :
    "s'additionnent" et "additionnent" doivent se retrouver.
    """
    decomposed = unicodedata.normalize("NFD", (word or "").lower())
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return "".join(c for c in stripped if c.isalnum())


def load_library():
    """{cle: {"usage": str, "files": [Path, ...]}} depuis le manifeste."""
    if not MANIFEST.exists():
        return {}
    try:
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    lib = {}
    for e in entries:
        path = SFX_DIR / e["file"]
        if not path.exists():
            continue
        slot = lib.setdefault(e["key"], {"usage": e.get("usage", ""), "files": []})
        slot["files"].append(path)
    return lib


def vocabulary_block():
    """Liste fermee inseree dans le prompt de decoupage.

    Generee depuis le manifeste : ajouter un son met le prompt a jour tout
    seul, en retirer un le rend immediatement inciteable. Le modele ne voit
    jamais un nom de fichier, seulement une cle - aucune hallucination
    possible.
    """
    lib = load_library()
    if not lib:
        return ""
    lines = [f"- {key} : {slot['usage']}" for key, slot in sorted(lib.items())]
    return "\n".join(lines)


def plan(segments, cues, seed=None):
    """Resout les bruitages en (instant, fichier, gain).

    segments : [(texte_parle, duree)] dans l'ordre du montage.
    cues     : meme longueur, chaque element valant {"cue":..., "word":...}
               ou None.

    Toute entree invalide est SILENCIEUSEMENT ignoree plutot que devinee :
    une cle inconnue, un mot absent du texte, un fichier manquant. Mieux vaut
    un bruitage en moins qu'un son pose au hasard.
    """
    lib = load_library()
    if not lib:
        return [], ["bibliotheque de bruitages vide ou introuvable"]

    rng = random.Random(seed)
    timeline = subtitles.word_timeline(segments)
    placed, warnings = [], []

    for scene, cue in enumerate(cues):
        if not isinstance(cue, dict):
            continue
        key = str(cue.get("cue", "")).strip().lower()
        word = str(cue.get("word", "")).strip()
        if not key:
            continue
        if key not in lib:
            warnings.append(f"scene {scene + 1} : cle inconnue {key!r}, ignoree")
            continue

        target = _normalize(word)
        moment = None
        if target:
            for sc, _i, w, start, _end, _words in timeline:
                if sc == scene and target in _normalize(w):
                    moment = start
                    break
        if moment is None:
            warnings.append(
                f"scene {scene + 1} : mot {word!r} absent du texte, {key} ignore"
            )
            continue

        # Variante tiree au sort : le meme fichier repete sonne robotique,
        # exactement ce qu'on cherche a eviter.
        path = rng.choice(lib[key]["files"])
        placed.append((max(0.0, moment - LEAD), path, GAIN.get(key, DEFAULT_GAIN)))

    placed.sort(key=lambda p: p[0])
    return _thin_out(placed, warnings), warnings


def _thin_out(placed, warnings):
    """Ecarte les bruitages en surdensite.

    Saturer sonne pire que ne rien mettre et couvre la narration. Le prompt
    demande deja de la retenue, mais une consigne ne se verifie pas toute
    seule.
    """
    kept = []
    for item in placed:
        recent = [k for k in kept if item[0] - k[0] < 10.0]
        if len(recent) >= MAX_PER_10S:
            warnings.append(f"bruitage a {item[0]:.1f}s ecarte (trop dense)")
            continue
        kept.append(item)
    return kept


def mix_into_audio(audio_path, placed, out_path):
    """Melange les bruitages a la narration deja montee.

    Opere sur l'AUDIO seul : la video n'est pas retouchee, donc le montage
    final peut continuer a la copier sans reencoder.
    """
    audio_path, out_path = Path(audio_path), Path(out_path)
    if not placed:
        return False

    inputs = ["-i", str(audio_path)]
    filters, labels = [], []
    for i, (moment, path, gain) in enumerate(placed, start=1):
        inputs += ["-i", str(path)]
        ms = int(moment * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},volume={gain:.3f}[s{i}]")
        labels.append(f"[s{i}]")

    # duration=first : la narration fixe la longueur, un bruitage pose en fin
    # de video ne doit jamais l'allonger (la garantie >=60s et le calage
    # video/audio reposent dessus).
    filters.append(
        "[0:a]" + "".join(labels)
        + f"amix=inputs={len(labels) + 1}:duration=first:normalize=0,"
        "alimiter=limit=0.95[out]"
    )

    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error"] + inputs
        + ["-filter_complex", ";".join(filters), "-map", "[out]", str(out_path)],
        check=False,
    )
    return result.returncode == 0 and out_path.exists()
