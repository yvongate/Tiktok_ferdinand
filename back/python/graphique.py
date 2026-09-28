"""Pipeline du format graphique : « POV : tu as investi 100 € en ... ».

Aucune génération d'image ni de vidéo par IA — seulement la voix. D'où un
coût d'environ deux centimes par vidéo contre ~0,80 $ pour le format
Ferdinand, et un temps dominé par le calcul local, pas par l'attente d'API.

La progression est écrite sur la sortie standard dans le MÊME format que
generate.py, pour que le backend n'ait qu'un seul analyseur à maintenir.

Usage :
    python graphique.py --subject '{"symbole":"BAYN.DE",...}' --out-dir ...
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import chart
import sfx as sfx_lib
import variation as variation_lib
import subtitles
import watermark

FPS = 24
MISE = 100
# La montée de la courbe et le maintien de l'image finale sont désormais
# tirés par vidéo (voir variation.REVELATION / variation.MAINTIEN) : un
# rythme identique à la seconde près sur 95 vidéos se remarque plus vite
# qu'une couleur.

# Bruitages posés sur les moments de la courbe, pas à intervalle régulier.
# Le riser démarre AVANT le sommet : un son de tension qui arrive après
# l'événement ne tend plus rien.
SONS = [
    ("debut", 0.10, "ding_1.wav", 0.22),
    ("avant_sommet", -5.0, "riser_1.wav", 0.16),
    ("sommet", 0.0, "impact.wav", 0.30),
    ("creux", 0.0, "subdrop_1.wav", 0.28),
    ("fin", 0.20, "cash_1.wav", 0.24),
]


# Repli : jeux de cinq phrases ecrits a l'avance, utilises quand l'appel a
# GPT echoue (reseau, quota, credits). Sans eux, une panne d'API ferait perdre
# la video entiere pour cinq phrases. Le vivier est volontairement fini et
# relu : mieux vaut une tournure deja vue qu'un allemand approximatif.
#
# Les umlauts sont ecrits normalement (Hoechststand -> Höchststand) : ces
# textes servent AUSSI de sous-titres, et un spectateur allemand lit
# immediatement « Hoechststand » comme une faute d'etranger. La
# translitteration datait d'un probleme d'encodage corrige depuis.
VIVIER = [
    ("Hundert Euro. {annee}.",
     "Der Höchststand: {sommet} Euro.",
     "Dann fällt {nom} auf {creux} Euro.",
     "{final} Euro heute.",
     "Und? Hättest du durchgehalten?"),
    ("{annee}. Du legst hundert Euro an.",
     "Ganz oben: {sommet} Euro.",
     "Danach geht es runter. Bis auf {creux} Euro.",
     "Heute sind es {final} Euro.",
     "Und du? Wärst du dabeigeblieben?"),
    ("Hundert Euro, {annee} investiert.",
     "Zwischendurch: {sommet} Euro.",
     "Dann verliert {nom}. {creux} Euro bleiben übrig.",
     "Stand heute: {final} Euro.",
     "Hättest du so lange gewartet?"),
    ("Stell dir vor, es ist {annee}.",
     "Dein bester Moment: {sommet} Euro.",
     "Und dann? Runter auf {creux} Euro.",
     "Am Ende: {final} Euro.",
     "Ehrlich: Hättest du verkauft?"),
]

# Meme logique pour la carte-titre. « POV: » reste, la formulation change.
TITRES = [
    ("POV: Du hast {annee}", "{mise} € in {nom} investiert"),
    ("POV: {annee}. Du legst", "{mise} € in {nom} an."),
    ("POV: Deine {mise} €", "liegen seit {annee} in {nom}"),
    ("POV: Du kaufst {annee}", "für {mise} € {nom}-Aktien"),
]


def _valeurs(sujet, reperes):
    return {
        "annee": reperes["annee_debut"],
        "nom": sujet["nom"],
        "sommet": round(reperes["sommet"]),
        "creux": round(reperes["creux"]),
        "final": round(reperes["final"]),
        "mise": MISE,
    }


def _minutage(textes, reperes, revelation):
    """Associe chaque phrase au moment de la courbe qu'elle commente.

    L'ordre est fixe (départ, sommet, creux, résultat, question finale) :
    c'est le minutage qui porte le sens, pas la formulation.
    """
    return [
        (0.4, textes[0]),
        (max(2.0, reperes["t_sommet"] - 1.6), textes[1]),
        (max(4.0, reperes["t_creux"] - 1.6), textes[2]),
        (revelation - 0.5, textes[3]),
        (revelation + 1.2, textes[4]),
    ]


def phrases(sujet, reperes, index, revelation):
    """Cinq phrases allemandes, calées sur les événements de la courbe.

    Volontairement courtes : ~25 mots sur 65 secondes. Le silence entre deux
    phrases pendant que la courbe s'effondre en dit plus qu'un commentaire.

    Écrites par GPT à partir des chiffres réels de CETTE vidéo, avec repli sur
    le vivier si l'appel échoue. Les cinq phrases étaient jusqu'ici figées
    dans le code : 95 vidéos au même texte près, le gabarit le plus
    reconnaissable de toute la chaîne.
    """
    v = _valeurs(sujet, reperes)
    ecrites = _par_modele(v)
    if ecrites:
        print("  Phrases ecrites par le modele.")
        return _minutage(ecrites, reperes, revelation)
    modele = _paquet_vivier(index)
    print("  (repli sur le vivier de phrases)")
    return _minutage([p.format(**v) for p in modele], reperes, revelation)


def _paquet_vivier(index):
    return variation_lib._paquet(VIVIER, index, "vivier")


def _par_modele(v):
    """Demande cinq phrases au modele. Renvoie None a la moindre anomalie.

    Controles volontairement stricts : ces phrases partent en synthese vocale
    ET en sous-titres, sans relecture humaine. Mieux vaut le vivier qu'une
    sortie de modele bancale.
    """
    consigne = (
        "You write the voice-over for a short German finance video showing what 100 EUR "
        "invested in one company became over time. Write EXACTLY 5 lines, one per line, "
        "no numbering, no quotes, no markdown.\n"
        "Line 1: the start - the year and the 100 euros.\n"
        "Line 2: the peak value.\n"
        "Line 3: the fall, naming the company.\n"
        "Line 4: the value today.\n"
        "Line 5: a short direct question to the viewer, asking whether they would have held on.\n"
        "RULES: German only, informal 'du', never 'Sie'. Each line at most 9 words. "
        "Spoken German, not written German. Use the exact numbers given, never invent others. "
        "Write umlauts normally (ä, ö, ü, ß). No emoji, no hashtags, no English."
    )
    donnees = (f"year={v['annee']} company={v['nom']} stake={v['mise']} EUR "
               f"peak={v['sommet']} EUR trough={v['creux']} EUR today={v['final']} EUR")
    import generate
    sortie = generate.claude(consigne, donnees, max_tokens=300, retries=2)
    if not sortie:
        return None
    lignes = [l.strip(" -•\t") for l in sortie.strip().splitlines() if l.strip()]
    if len(lignes) != 5:
        print(f"  ATTENTION : {len(lignes)} phrase(s) au lieu de 5, vivier utilise.")
        return None
    if any(len(l.split()) > 12 or len(l) > 90 for l in lignes):
        print("  ATTENTION : phrase trop longue pour un sous-titre, vivier utilise.")
        return None
    # Les chiffres doivent etre ceux de la serie, pas ceux du modele.
    attendus = {str(v["sommet"]), str(v["creux"]), str(v["final"])}
    presents = {n for n in re.findall(r"\d+", " ".join(lignes))}
    if not attendus <= presents:
        print("  ATTENTION : chiffres inexacts dans la sortie du modele, vivier utilise.")
        return None
    return lignes


def titre_lignes(sujet, reperes, index):
    """Les deux lignes de la carte-titre, formulation variable."""
    v = _valeurs(sujet, reperes)
    return [l.format(**v) for l in variation_lib._paquet(TITRES, index, "titre")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--subject", required=True,
                   help="JSON du sujet impose par le backend (nom, symbole, annees)")
    p.add_argument("--lang", default="de")
    p.add_argument("--out-dir", default=".")
    p.add_argument("--cache-dir", default=None,
                   help="Dossier des voix deja produites, partage entre les tentatives "
                        "d'un meme sujet (voir generate.py).")
    p.add_argument("--no-subtitles", action="store_true")
    p.add_argument("--no-sfx", action="store_true")
    p.add_argument("--watermark", default=None)
    # Options du format Ferdinand, acceptees et ignorees : le backend lance
    # les deux scripts avec la meme base d'arguments.
    args, _ignores = p.parse_known_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    sujet = json.loads(args.subject)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir) if args.cache_dir else out
    cache.mkdir(parents=True, exist_ok=True)
    suffixe = f"_{sujet['symbole'].replace('.', '_')}"

    # La cle API est verifiee MAINTENANT, avant tout travail : sans elle, la
    # voix echouera de toute facon, et decouvrir le probleme apres le
    # chargement des donnees ne rend service a personne.
    import generate
    generate.api_key()

    # Tout ce qui distingue cette video des 94 autres, tire une fois ici.
    # L'index est le rang du sujet dans la liste validee : il donne la
    # position dans le paquet battu, donc deux videos publiees a la suite
    # n'ont ni la meme palette, ni le meme rythme, ni la meme voix.
    index = int(sujet.get("n", 0))
    var = variation_lib.pour(sujet["symbole"], index, args.lang)

    print(f"=== Mode : graphique / Langue : {args.lang} ===\n")
    print(f"  Variation : {var.resume_graphique()}")

    # --- 1. Donnees -----------------------------------------------------
    print("=== 1. Generation de l'idee ===")
    titre = f"{sujet['nom']} — {sujet['annees']} ans"
    print(f"-> Idee imposee : {titre}")
    try:
        donnees = chart.charger(sujet["symbole"], sujet["annees"], MISE)
    except ValueError as e:
        # Message reconnu par diagnose.ts : « serie invalide », « serie vide »,
        # « aucun taux de change ». Un traceback brut n'aurait rien dit a
        # l'ecran, alors que le geste a faire est precis (retirer le sujet).
        print(f"ECHEC total : donnees boursieres inexploitables - {e}. Arret.")
        return 1
    import datetime
    # fromtimestamp(..., timezone.utc) : utcfromtimestamp est deprecie depuis
    # Python 3.12 et emet un avertissement au milieu de la progression.
    horo = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    vals = [v for _, _, v in donnees]
    i_hi = max(range(len(vals)), key=lambda i: vals[i])
    i_lo = min(range(len(vals)), key=lambda i: vals[i])
    reperes = {
        "annee_debut": horo(donnees[0][0]).year,
        "sommet": vals[i_hi], "creux": vals[i_lo], "final": vals[-1],
        "t_sommet": i_hi / (len(vals) - 1) * var.revelation,
        "t_creux": i_lo / (len(vals) - 1) * var.revelation,
    }
    print(f"  {len(donnees)} seances | {MISE:.0f} -> {vals[-1]:.2f} EUR "
          f"| sommet {reperes['sommet']:.2f}")

    # --- 2. Voix --------------------------------------------------------
    print("\n=== 2. Generation du script ===")
    textes = phrases(sujet, reperes, index, var.revelation)

    # Une seule echelle d'avancement pour les deux phases. Les voix etaient
    # numerotees sur 5 et l'animation sur 1560 : le backend interpole sur
    # courant/total, si bien que la barre passait de 74 % a 18 % en changeant
    # de phase. Verifie : « Scene 5/5 » -> 74 %, « Scene 120/1560 » -> 18 %.
    n_rev = int(var.revelation * FPS)
    n_tot = n_rev + int(var.maintien * FPS)
    JALON = 120                                   # une ligne toutes les 5 s
    etapes_anim = (n_tot + JALON - 1) // JALON
    etapes = len(textes) + etapes_anim

    lignes = []
    for i, (debut, texte) in enumerate(textes, 1):
        print(f"\n=== Scene {i}/{etapes} : voix ===")
        # Dans le cache : une relance ne doit pas repayer les voix deja
        # produites pour ce meme sujet.
        wav = cache / f"voix_{i:02d}.wav"
        if not wav.exists() and not generate.generate_voice(texte, wav, lang=args.lang,
                                                profil=var.profil_voix, timbre=var.timbre):
            print("  Echec voix de la scene.")
            continue
        duree = generate.get_duration(wav)
        print(f"  Voix OK ({duree:.2f}s) : {texte[:60]!r}")
        lignes.append((debut, duree, texte, wav))

    # --- 3. Animation ---------------------------------------------------
    print(f"\n=== 4. Generation scene par scene ===")
    # La garde portait sur la VIDEO source, absente du depot (*.mp4 est
    # ignore par git) : le medaillon n'etait donc jamais rendu, ni en local ni
    # sur Render, alors que les 72 images decoupees sont bien la. C'est leur
    # presence qui compte - chart.medaillon() ne retouche la video que si
    # elles manquent.
    source = Path(__file__).parent / "_ferdinand_source.mp4"
    images = Path(__file__).parent / "_medaillon"
    if any(images.glob("f_*.png")) or source.exists():
        badges = chart.medaillon(source, taille=var.medaillon)
        print(f"  Medaillon Ferdinand : {len(badges)} images")
    else:
        badges = []
        print("  ATTENTION : aucune image de medaillon, Ferdinand sera absent.")

    # Logo de l'entreprise : filigrane derriere le trace, et pastille a la
    # pointe de la courbe. Facultatif - sans fichier, le rendu est celui
    # d'avant, sans aucune degradation.
    embleme = chart.logo(sujet["symbole"])
    print(f"  Logo {sujet['symbole']} : "
          + ("trouve" if embleme is not None else "absent, graphique sans logo"))
    rendu = chart.Rendu(
        donnees, sujet["nom"], reperes["annee_debut"], MISE, badges,
        palette={"fond": var.fond, "grille": var.grille, "gain": var.gain,
                 "perte": var.perte, "accent": var.accent, "repere": var.repere},
        titre_lignes=titre_lignes(sujet, reperes, index),
        logo_img=embleme)
    muet = out / f"anim{suffixe}.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{chart.L}x{chart.H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", str(muet)],
        stdin=subprocess.PIPE)

    t0 = time.perf_counter()
    try:
        for i in range(n_tot):
            av = min(1.0, max(0.004, (i + 1) / n_rev))
            # Pendant le maintien la courbe est figee, mais le medaillon
            # continue de bouger : sinon l'image finale ressemble a un plantage.
            ff.stdin.write(rendu.image(av, frame=i).tobytes())
            if (i + 1) % JALON == 0:
                # Numerotation continue avec les voix (voir `etapes`).
                print(f"=== Scene {len(textes) + (i + 1) // JALON}/{etapes} : video ===")
        ff.stdin.close()
    except BrokenPipeError:
        # FFmpeg est mort en cours de route : sans ce filet, le script
        # remontait un traceback que diagnose.ts classait « cause inconnue ».
        print("ECHEC total : FFmpeg a ferme le flux pendant l'animation. Arret.")
        ff.wait()
        return 1
    ff.wait()
    if ff.returncode != 0 or not muet.exists():
        print(f"ECHEC total : encodage de l'animation echoue (code {ff.returncode}). Arret.")
        return 1
    print(f"  Animation OK ({time.perf_counter() - t0:.0f}s)")

    # --- 4. Montage -----------------------------------------------------
    print("\n=== 5. Montage FFmpeg ===")
    total = n_tot / FPS

    incrustations = []
    if not args.no_subtitles and lignes:
        segments, horloge = [], 0.0
        for debut, duree, texte, _ in lignes:
            if debut > horloge:
                segments.append(("", debut - horloge))
            segments.append((texte, duree))
            horloge = debut + duree
        ass = out / f"subs{suffixe}.ass"
        # y=350 : sous la carte-titre. La valeur par defaut (980) tomberait
        # dans le trace et chevaucherait l'etiquette « Investi ».
        if subtitles.build_ass(segments, ass, y=var.y_graphique,
                               actif=var.couleur_active,
                               inactif=var.couleur_inactive):
            incrustations.append(subtitles.ass_filter(ass))

    if watermark.configured(args.watermark):
        wm = out / f"wm{suffixe}.ass"
        if watermark.build_ass(total, wm, override=args.watermark,
                               waypoints=var.waypoints):
            incrustations.append(subtitles.ass_filter(wm))

    entrees, filtres, etiquettes = ["-i", str(muet)], [], []
    for debut, _, _, wav in lignes:
        entrees += ["-i", str(wav)]
        ms = int(debut * 1000)
        idx = len(etiquettes) + 1
        filtres.append(f"[{idx}:a]adelay={ms}|{ms}[a{idx}]")
        etiquettes.append(f"[a{idx}]")

    if not args.no_sfx:
        dossier = sfx_lib.SFX_DIR
        ancres = {"debut": 0.0, "avant_sommet": reperes["t_sommet"],
                  "sommet": reperes["t_sommet"], "creux": reperes["t_creux"],
                  "fin": var.revelation}
        for ancre, decalage, fichier, gain in SONS:
            chemin = dossier / fichier
            if not chemin.exists():
                continue
            t = max(0.0, ancres[ancre] + decalage)
            entrees += ["-i", str(chemin)]
            ms = int(t * 1000)
            idx = len(etiquettes) + 1
            filtres.append(f"[{idx}:a]adelay={ms}|{ms},volume={gain}[a{idx}]")
            etiquettes.append(f"[a{idx}]")

    final = out / f"final{suffixe}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error"] + entrees
    if etiquettes:
        filtres.append("".join(etiquettes)
                       + f"amix=inputs={len(etiquettes)}:normalize=0,"
                         f"apad,atrim=0:{total},alimiter=limit=0.95[aout]")
        cmd += ["-filter_complex", ";".join(filtres), "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-map", "0:v"]
    if incrustations:
        cmd += ["-vf", ",".join(incrustations), "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-t", str(total), str(final)]

    if subprocess.run(cmd, check=False).returncode != 0 or not final.exists():
        # "ECHEC total" et non "ECHEC :" : le second est classe comme un refus
        # de tache API par le backend, ce que ce montage local n'est pas.
        print("ECHEC total : montage final impossible. Arret.")
        return 1

    # Meme bilan que generate.py : une voix ratee laisse une video muette a cet
    # endroit-la, ce que rien d'autre ne signale.
    print(f"\n=== BILAN : {len(lignes)}/{len(textes)} scenes produites ===")
    if len(lignes) < len(textes):
        print(f"ATTENTION : {len(textes) - len(lignes)} phrase(s) sans voix.")

    print(f"\n=== TERMINE : {final} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
