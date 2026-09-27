"""
Faux generate.py : reproduit exactement le format de sortie du vrai script,
en quelques secondes et sans aucun appel API. Sert uniquement a tester
l'orchestration du backend (parsing de progression, SSE, livraison video)
sans consommer de credits. Ne fait PAS partie du pipeline de production.

Usage identique au vrai script : --mode --lang --video-model --out-dir

Variable d'environnement MOCK_FAULTS pour rejouer des pannes (les memes
lignes que le vrai script), afin de tester l'affichage des incidents :
  MOCK_FAULTS=retries   retries reseau + tache fournisseur echouee + rejet
  MOCK_FAULTS=fatal     arret sur echec total
  MOCK_FAULTS=quota     arret sur HTTP 429
  MOCK_FAULTS=stall     silence prolonge (declenche le watchdog)
Plusieurs valeurs separees par des virgules.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--mode", default="short")
p.add_argument("--lang", default="fr")
p.add_argument("--video-model", default="runway")
p.add_argument("--out-dir", default=".")
p.add_argument("--idea", default=None)

# parse_known_args et non parse_args : toute option ajoutee au vrai script
# sans l'etre ici faisait echouer TOUS les jobs sur un "unrecognized
# arguments" invisible depuis l'interface. C'est arrive trois fois
# (--no-subtitles, --no-sfx, --watermark) ; on ignore desormais ce qu'on ne
# connait pas plutot que de le repeter.
args, ignores = p.parse_known_args()

FAULTS = {f.strip() for f in os.environ.get("MOCK_FAULTS", "").split(",") if f.strip()}

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

out = Path(args.out_dir)
out.mkdir(parents=True, exist_ok=True)
N_SCENES = 4
# MOCK_STEP ralentit le deroule pour observer l'interface pendant qu'elle vit
# (le defaut reste rapide, pour les tests automatises).
STEP = float(os.environ.get("MOCK_STEP", "0.25"))

print(f"=== Mode : {args.mode} / Langue : {args.lang} / Video : {args.video_model} ===\n")

print("=== 1. Generation de l'idee ===")
time.sleep(STEP)
if args.idea:
    print(f"-> Idee imposee : {args.idea}")
else:
    print("1. Voici pourquoi ton salaire disparait si vite")
    print("-> Idee choisie : Voici pourquoi ton salaire disparait si vite")
time.sleep(STEP)

if "quota" in FAULTS:
    print("  HTTP 429: {\"error\":\"rate limit exceeded, retry later\"}")
    print("  (retry 1/4 apres echec GPT-5.2)")
    print("ECHEC total sur la generation d'idees. Arret.")
    sys.exit(1)

print("\n=== 2. Generation du script ===")
if "retries" in FAULTS:
    print("  Erreur reseau (TimeoutError): timed out")
    print("  (retry 1/4 apres echec GPT-5.2)")
    time.sleep(STEP)
    print("  (tentative 2/3 rejetee : ne commence pas par \"Voici pourquoi\" -> \"Le salaire...\")")
    time.sleep(STEP)
if "fatal" in FAULTS:
    print("ECHEC : le script ne commence jamais correctement apres 3 tentatives. Arret.")
    sys.exit(1)
print("[curious] Voici pourquoi ton salaire disparait si vite.")
time.sleep(STEP)

if args.mode == "60s":
    print("  Controle duree : 56.8s")
    time.sleep(STEP)
    print("  Duree 56.8s < 60s cible - regeneration d'un script plus etoffe (tentative 2/4)")
    print("  Nouvelle duree : 82.2s")
    time.sleep(STEP)

print(f"  -> ~{N_SCENES} scenes visees (indicatif ...)")
print("\n=== 3. Decoupage en scenes (avec texte parle par scene) ===")
print(f"{N_SCENES} scenes generees.")
time.sleep(STEP)

print("\n=== 4. Generation scene par scene (voix individuelle + image + video calee sur sa duree) ===")
for n in range(1, N_SCENES + 1):
    for stage in ("voix", "image", f"video ({args.video_model})"):
        print(f"\n=== Scene {n}/{N_SCENES} : {stage} ===")
        time.sleep(STEP)
        if "retries" in FAULTS and n == 2 and stage.startswith("video"):
            # Battements de coeur puis echec cote fournisseur, comme le vrai
            # wait_for_result() / create_and_wait().
            print("    ATTENTE 24s/300s (etat=waiting)")
            time.sleep(STEP)
            print("    ATTENTE 48s/300s (etat=waiting)")
            time.sleep(STEP)
            print("    ECHEC : internal error, please try again later")
            print(f"    (tache {args.video_model} echouee, nouvelle tentative 2/3)")
            time.sleep(STEP)
        if "retries" in FAULTS and n == 3 and stage == "voix":
            print("  Erreur telechargement (RemoteDisconnected): connexion coupee - (retry 1/4)")
            time.sleep(STEP)
        if "stall" in FAULTS and n == 2 and stage == "image":
            # Plus aucune sortie : le watchdog du backend doit le signaler.
            print("  (simulation de blocage : plus aucune sortie pendant 4 min)")
            time.sleep(240)
    print(f"  Video OK -> {out / f'scene_{n:02d}.mp4'} (calee sur 4.20s)")

print("\n=== 5. Montage FFmpeg ===")
final = out / "final_mock.mp4"
subprocess.run(
    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=darkred:s=360x640:d=3",
     "-pix_fmt", "yuv420p", str(final)],
    check=False,
)
print(f"  Fusion audio OK -> {final}")
print(f"\n=== TERMINE : {final} ===")
