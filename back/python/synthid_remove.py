"""
Regeneration des pixels de la video finale par un service GPU distant
(ex. Modal), en option.

DESACTIVEE PAR DEFAUT (`SYNTHID_REMOVE=1` pour l'activer).

A quoi ca sert : chaque image est re-synthetisee a travers un VAE avec du
bruit injecte dans l'espace latent. Les pixels de sortie ne sont plus ceux
du modele video d'origine, ce qui perturbe tout signal invisible qui y
serait cache. C'est une perturbation GENERIQUE : le code vient d'un projet
calibre contre SynthID (Google), mais le mecanisme ne cible aucun filigrane
en particulier.

Ce qu'on ne peut PAS promettre : ni Google ni ByteDance ni Runway ne
publient de detecteur, donc l'efficacite reelle sur une video Runway ou
Seedance est invérifiable - dans un sens comme dans l'autre. A ne pas
confondre avec ai_metadata.py, qui traite les metadonnees du conteneur
(chose differente, elle verifiable, et deja en place).

Deux reserves avant d'activer :
  - Les sous-titres sont incrustes AVANT cette etape dans generate.py. Un
    VAE reconstruit mal le texte fin : attendre un rendu plus mou sur les
    sous-titres animes.
  - Le cout GPU est reel (facture a la seconde) et le service ajoute un
    aller-retour reseau de la taille de la video.

Mode distant uniquement : le mode local (torch/diffusers dans ce process) a
ete retire, il n'etait pas executable en production (pas de GPU sur Render,
~1 min/image sur CPU) et dupliquait du code tiers que personne ne lancait.
Le VAE vit cote service, voir `back/modal/app.py` du projet
github.com/yvongate/remove-ai-matadata.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def is_enabled() -> bool:
    """True seulement si SYNTHID_REMOVE est mis ET un service est configure :
    sans URL il n'y a plus rien a appeler depuis le retrait du mode local."""
    flag = os.environ.get("SYNTHID_REMOVE", "").strip().lower() in {"1", "true", "yes"}
    return flag and bool(os.environ.get("SYNTHID_REMOTE_URL"))


def _probe(path: Path) -> tuple[int, int, float]:
    """Dimensions et fps reels de la source. Le service applique
    `min(fps_demande, fps_source)` et redimensionne sur `long_side` : envoyer
    les valeurs de la source evite a la fois de perdre des images et de
    payer un upscale inutile. Defauts alignes sur le pipeline (1080x1920@24)
    si ffprobe est muet."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,avg_frame_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=False,
        ).stdout
        s = (json.loads(out).get("streams") or [{}])[0]
        num, _, den = (s.get("avg_frame_rate") or "24/1").partition("/")
        fps = float(num) / float(den or 1)
        return int(s["width"]), int(s["height"]), (fps if fps > 0 else 24.0)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return 1080, 1920, 24.0


def _multipart_body(fields: dict, file_field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
    )
    parts.append(data)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _headers() -> dict:
    key = os.environ.get("SYNTHID_REMOTE_KEY")
    return {"x-api-key": key} if key else {}


def remove(input_path, output_path, *, duration: float | None = None) -> bool:
    """Envoie la video au service GPU, attend le resultat, le telecharge.
    Renvoie False (jamais d'exception) si quoi que ce soit echoue - la video
    d'origine reste utilisable dans ce cas."""
    input_path, output_path = Path(input_path), Path(output_path)
    base = os.environ.get("SYNTHID_REMOTE_URL", "").rstrip("/")
    if not base:
        print("    (SynthID : SYNTHID_REMOTE_URL absent, etape ignoree)")
        return False

    headers = _headers()
    timeout_s = float(os.environ.get("SYNTHID_REMOTE_TIMEOUT_S", "3600"))
    poll_s = float(os.environ.get("SYNTHID_REMOTE_POLL_MS", "3000")) / 1000.0
    deadline = time.monotonic() + timeout_s

    width, height, fps = _probe(input_path)
    long_side = int(os.environ.get("SYNTHID_LONG_SIDE", str(max(width, height))))

    fields = {
        "noise_std": os.environ.get("SYNTHID_NOISE_STD", "0.15"),
        "long_side": str(long_side),
        "fps": str(fps),
        "seed": "0",
        "model": "stabilityai/sd-vae-ft-mse",
    }
    if duration is not None:
        fields["duration"] = str(duration)

    print(f"    SynthID : envoi au service GPU ({width}x{height}@{fps:.0f}fps, "
          f"long_side={long_side})...")

    try:
        body, boundary = _multipart_body(fields, "file", input_path.name, input_path.read_bytes())
        req = urllib.request.Request(f"{base}/submit", data=body, headers={
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })
        with urllib.request.urlopen(req, timeout=120) as r:
            submit = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"    (SynthID : envoi echoue - {e})")
        return False

    call_id = submit.get("call_id")
    if not call_id:
        print(f"    (SynthID : reponse inattendue - {submit})")
        return False

    while True:
        if time.monotonic() > deadline:
            print("    (SynthID : delai depasse)")
            return False
        time.sleep(poll_s)
        try:
            req = urllib.request.Request(f"{base}/status/{call_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                status = json.loads(r.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            print(f"    (SynthID : etat indisponible - {e})")
            return False
        if status.get("status") == "error":
            print(f"    (SynthID : echec cote GPU - {status.get('error')})")
            return False
        if status.get("status") == "done":
            if status.get("metrics"):
                print(f"    SynthID : {status['metrics']}")
            break

    try:
        req = urllib.request.Request(f"{base}/result/{call_id}", headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            output_path.write_bytes(r.read())
    except (urllib.error.URLError, OSError) as e:
        print(f"    (SynthID : telechargement echoue - {e})")
        return False

    return output_path.exists()
