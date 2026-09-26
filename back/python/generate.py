"""
Pipeline complet : genere une video "Voici pourquoi..." de bout en bout
(finance / psychologie de l'argent, rendu 3D photorealiste style Zack D
Films, mascotte recurrente Ferdinand), via KIE.AI (GPT-5.2, nano-banana,
Runway/Seedance, Gemini 3.1 Flash TTS) + FFmpeg local pour le montage.

Voir GENERATION_GUIDE.md (video-vision/) pour la doc complete et a jour -
ce docstring n'en est qu'un resume rapide.

Architecture : la voix est generee SEPAREMENT pour chaque scene (pas un
seul bloc pour tout le script), avec sa duree reelle mesuree individuellement
et le clip video cale dessus (rogne ou image gelee) - pour une synchro
scene/audio precise. "mode" ne cible plus une duree fixe, seulement
l'ampleur narrative :
  - "short" (defaut) : histoire resserree, pas d'exemple, pas de duree
                        minimale garantie
  - "60s"            : histoire complete avec exemple optionnel, DUREE
                        >=60s GARANTIE (regeneration auto si trop court) -
                        pense pour l'eligibilite monetisation TikTok

Usage:
    python generate.py                              # mode court, EN, Runway (defauts)
    python generate.py --mode 60s --lang fr          # mode 60s garanti, francais
    python generate.py --video-model seedance        # repli si Runway indisponible
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import http.client
from pathlib import Path

import sfx
import subtitles


def _load_api_key():
    """Cle API KIE.AI. Priorite a la variable d'environnement (indispensable
    pour l'hebergement : pas de chemin absolu Windows en dur), avec repli sur
    un fichier local pour l'usage en developpement."""
    env_key = os.environ.get("KIE_API_KEY")
    if env_key:
        return env_key.strip().split(":")[-1].strip()
    for candidate in (
        Path(__file__).parent / "api.txt",
        Path(r"F:\Tiktok\api.txt"),
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip().split(":")[-1].strip()
    raise SystemExit(
        "Cle API introuvable : definis la variable d'environnement KIE_API_KEY "
        "ou place un fichier api.txt a cote de ce script."
    )


API_KEY = _load_api_key()
# OUT_DIR est fixe par --out-dir (chaque job du backend ecrit dans son propre
# dossier) ; par defaut, a cote du script comme avant en usage CLI direct.
OUT_DIR = Path(__file__).parent

SCENE_CLIP_SECONDS = 5  # duree fixe par scene (Seedance/Runway)

# Constat du 24/09 : predire la duree de la voix a partir d'un nombre de mots
# ne marche pas de facon fiable (langue, debit, pauses, balises d'emotion...) -
# ex. un script FR de 116 mots a dure 56s reel au lieu des ~35-40s "attendus"
# par l'ancienne cible de mots. Plutot que deviner, le pipeline genere
# maintenant la voix AVANT le decoupage en scenes (voir main()), mesure sa
# duree REELLE, et en deduit le nombre de scenes necessaire
# (n_scenes = duree_audio / SCENE_CLIP_SECONDS). "mode" ne controle donc plus
# une duree ciblee, seulement l'AMPLEUR de l'histoire (structure narrative).
MODES = {
    "short": {
        "story_scope": "a tight explanation: hook, the relatable feeling, the hidden reason, and the payoff+CTA - skip the optional example (step 4).",
        "words_hint": "roughly 70-110 words as a rough feel for length - NOT a hard limit, just a guide to keep it tight. Let it breathe naturally rather than padding or cutting words to hit a number.",
    },
    "60s": {
        "story_scope": "a fuller explanation: hook, the relatable feeling, the hidden reason (with more depth), an optional short example (step 4), and the payoff+CTA.",
        "words_hint": "roughly 140-190 words as a rough feel for length - NOT a hard limit, just a guide for a fuller explanation. Let it breathe naturally rather than padding or cutting words to hit a number.",
    },
}

STYLE_LOCK = (
    "semi-realistic 3D CGI, GTA V / The Last of Us cutscene quality, realistic skin "
    "texture with visible pores, natural cinematic lighting, detailed real-world "
    "environment, photorealistic 3D render, no cartoon, no cel shading, no Pixar, "
    "no simple background, no studio backdrop"
)

# Mascotte recurrente de la chaine (demande explicite utilisateur, en
# remplacement de Picsou/Scrooge McDuck - meme esprit "riche et malin" mais
# design 100% original, aucun probleme de droits d'auteur). Description FIXE
# reutilisee mot pour mot sur TOUTES les videos (pas juste au sein d'une
# meme video) pour construire une identite de marque reconnaissable.
CHARACTER = (
    "Ferdinand, an anthropomorphic red fox standing and posing like a human, "
    "sleek reddish-orange fur with a white muzzle and chest and black-tipped "
    "ears and paws, sharp intelligent amber eyes, wearing a tailored deep-red "
    "three-piece suit with a gold pocket-watch chain and a black silk pocket "
    "square, sleek well-groomed fur, confident bourgeois posture, no logos"
)

# NICHE : finance / investissement / economie / psychologie de l'argent.
# Format "VOICI POURQUOI" (pivot demande explicitement par l'utilisateur, qui
# a fourni sa propre liste de ~80 titres comme reference - voir conversation
# du 25/09). Chaque video part d'une sensation/observation ultra-banale sur
# l'argent que tout le monde a deja vecue, et revele la raison cachee
# derriere. Ce n'est PLUS le format "Tom accumule des chiffres" d'avant -
# beaucoup de ces sujets sont des mecanismes psychologiques/commerciaux qui
# n'ont pas besoin d'une histoire chiffree pour etre clairs.
def build_idea_system(lang="en"):
    trigger_phrase = "Voici pourquoi" if lang == "fr" else "Here's why"
    return f"""You are a YouTube Shorts idea strategist for a French-style finance/money-psychology channel with one strong, recognizable format: every single title starts with the exact phrase "{trigger_phrase}", followed by a short, ultra-relatable everyday feeling or observation about money that almost everyone has personally had - the video then reveals the hidden reason behind it.

TASK: Generate 10 video titles, each starting with "{trigger_phrase}".

THE PATTERN (critical): the title itself must be the literal relatable trigger sentence a normal person would say or think (e.g. "{trigger_phrase} your paycheck never feels like enough", "{trigger_phrase} you buy things you don't need") - not an abstract topic name. It must describe a mundane, universally-felt experience, addressed directly to the viewer ("you"/"your"). The video's job is to reveal the hidden mechanism (psychological, business-strategy, banking, or economic) behind that everyday feeling.

Rotate across these angles (do not use the same angle for all 10 - spread across at least 5 of them):
1. Everyday money & life - common money frustrations (spending, saving, feeling broke, prices feeling higher)
2. Consumption psychology - pricing tricks, promotions, store/app design that makes you spend
3. Brain & money - cognitive biases (loss aversion, instant gratification, social proof, stress spending)
4. Banks & credit - how loans, interest, overdrafts, and installment payments really work
5. Internet & tech - the attention economy, why apps are "free", data, subscriptions
6. Work & wealth - salary vs wealth, assets vs income, why income alone isn't wealth
7. Strong curiosity - sharply counterintuitive money facts
8. Local everyday life (only when it fits naturally, do not force every video here) - local prices, local currency, local everyday scenes

Requirements: understood instantly in under 1 second, triggers strong personal recognition ("that's literally me") or curiosity, highly visual, feels like something the viewer has actually felt before.
Avoid: generic personal-finance advice ("save more", "budget better"), abstract institutional topics with no personal relatable angle, long titles.
Title rules: the full title (trigger phrase + observation) stays under 12 words, casual spoken language, no explanations, no jargon.

Output: return ONLY the 10 titles, one per line, numbered 1 to 10, spanning at least 5 different angles above. Nothing else, no preamble."""

def build_script_system(mode_cfg, lang="en"):
    # Format "VOICI POURQUOI" (voir build_idea_system) - explication d'une
    # sensation/observation quotidienne sur l'argent, PAS une histoire
    # chiffree a la "Tom accumule des gains". Les chiffres restent utiles
    # comme illustration ponctuelle, mais ne sont plus le moteur du script -
    # feedback explicite : l'ancienne version etait "trop dans les nombres".
    trigger_phrase = "Voici pourquoi" if lang == "fr" else "Here's why"
    lang_instruction = ""
    if lang == "fr":
        lang_instruction = """
LANGUAGE (critical): the video idea given to you may be phrased in English - that's fine, translate the concept naturally. But write your ENTIRE output script in FRENCH, not English. Natural, spoken, everyday French - not a literal word-for-word translation style. The SIMPLE VOCABULARY RULE below still applies in French (simple everyday French words a teenager understands, technical terms explained in plain French).
"""
    return f"""You are a YouTube Shorts scriptwriter for a French-style finance/money-psychology channel built around one recognizable format: "{trigger_phrase} [relatable everyday feeling about money]", then a clear explanation of the hidden reason behind it.
{lang_instruction}
TASK: Write a script for the video idea the user gives you (a "{trigger_phrase}..." title).

CORE TECHNIQUE - this is what makes these videos easy to understand, follow it precisely:
This is an EXPLANATION of a relatable everyday phenomenon, NOT a story about a named character accumulating numbers. Address the viewer directly ("you"/"your", or "tu"/"ton" in French). Only bring in an illustrative example (a generic person, a real company like a bank or an app, or a simple "imagine you...") if it genuinely makes the mechanism clearer - never force a named character or a chain of numbers into a topic that doesn't need one.

Follow this structure:
1. HOOK (1 sentence, mandatory, opens the script almost verbatim as the video's title): starts with "{trigger_phrase}" followed by the exact relatable everyday feeling/observation (e.g. "{trigger_phrase} your paycheck never feels like enough").
2. THE RELATABLE FEELING (1-2 sentences): describe the everyday experience so the viewer instantly recognizes themselves in it - concrete and specific, but no character or invented numbers needed here, just a vivid, familiar situation.
3. THE HIDDEN REASON (2-4 sentences): reveal the real underlying mechanism - a psychological bias, a business/pricing strategy, a banking mechanism, or an economic principle - explained in the simplest possible terms. Use a number ONLY if one genuinely helps illustrate the mechanism (e.g. a typical price, rate, or percentage) - never invent a chain of numbers for their own sake.
4. OPTIONAL SHORT EXAMPLE (0-2 sentences, only if it truly clarifies): a brief concrete illustration - can reference a real-world type of actor (a bank, a store, an app) or a generic "imagine someone who..." - not a mandatory named character, and not a running numeric story.
5. PAYOFF / REFRAME (1 sentence): a punchy closing insight that changes how the viewer will see this everyday moment from now on.
6. CALL TO ACTION (mandatory, exactly 1 short sentence, always last): unlike generic Shorts, this niche's viewers respond to a warm, personal, low-hype ask to follow/subscribe - never a generic "smash that subscribe button" line. Always start with a short "if you enjoyed/liked this" conditional clause, then the effort/behind-the-scenes ask: mention the real work behind making the video and ask for a follow in return (e.g. "If you enjoyed this, following means a lot - these videos take hours to make."). Vary the exact wording each time (never reuse the same sentence twice) but always keep both parts: the "if you liked it" clause AND the effort ask - never switch to a "more content" pitch or any other angle. Keep it under 15 words, warm and humble in tone, not salesy or hyped.

NUMBERS RULE (relaxed - this is the opposite of the old rule, read carefully): numbers are optional seasoning, not the point of the video. Use a concrete number only when it genuinely makes the mechanism easier to picture (e.g. "prices ending in .99", "a typical 20% interest rate") - never pad the script with numbers, never force a running/compounding numeric story, and never invent precise figures that aren't needed to understand the point. Clarity and relatability matter far more than numeric precision here.

For a COMPARISON idea (e.g. two people with the same salary ending up differently): keep it simple - describe both paths in a sentence or two each, without forcing a checkpoint-by-checkpoint numeric table.

SIMPLE VOCABULARY RULE (critical - a 13-year-old with no finance background must understand every sentence on first listen):
- Use only everyday, common words. Write the way you'd explain it out loud to a teenager, not the way a bank or a news article would write it.
- Never use a financial/legal/technical term without immediately explaining what it means in plain words, in the same breath. Do not assume the viewer knows what "securities", "assets", "liquidity", "equity", "amortization", "estate", "trust", "regulator", "collateral", etc. mean - either replace them with a plain-language equivalent, or add a short plain-language clarification right after the term (e.g. instead of "the bank sells securities" say "the bank sells stocks and bonds it owns" or "the bank sells investments it owns"; instead of "pledges eligible assets" say "hands over valuable stuff as a guarantee").
- THE HIDDEN REASON (step 3) is the one place a real technical/legal term is allowed and expected (that's the "aha" fact being taught) - but even there, immediately follow it with one plain-word explanation of what it actually means in practice.
- Prefer short concrete nouns over abstract ones (say "the money" not "the capital", say "a company" not "an entity", say "borrows money" not "secures financing").
- If a sentence needs a teenager to have heard the word before to understand it, rewrite the sentence.

AUDIO DELIVERY TAGS (the voice engine supports these - use them, but sparingly): you may insert short bracketed delivery tags right before the words they should affect, e.g. [whispers], [shouting], [urgency], [confidently], [curious], [enthusiastic]. Use ONLY 2 to 4 of them in the whole script, placed only at genuine emotional turning points - never on every sentence, never more than one per sentence. Suggested placements (skip any that don't fit naturally):
- HOOK: a curiosity tag like [curious] or [intriguing] on the opening "{trigger_phrase}..." line.
- THE HIDDEN REASON reveal: [whispers] or [confidently] works well for the "here's the actual reason" moment.
- PAYOFF: a [dramatic] tag on the final reframing line.
Always write the tag itself in English exactly as shown (e.g. [whispers]), even when the rest of the script is written in French or another language - only the surrounding words are translated, the tag keyword never is. Tags are delivery instructions, not spoken words - they do not count toward the word limit below.

STORY SCOPE for this video: {mode_cfg['story_scope']}
Length feel: {mode_cfg['words_hint']}

Style rules:
- Short punchy sentences, maximum 8-10 words each
- Use connectors like So / Then / Now / But / Until / Because / You see to chain sentences causally
- Slightly dramatic tone, no filler words, no bullet points, no section labels
- No moral lecture - end on the strongest insight (step 5), then the short follow ask (step 6)
- Do not pad the script with filler to reach a word count, and do not rush/cut content to stay under one - write exactly what the explanation needs, at a natural spoken pace. The video's length will be built AROUND however long this script naturally takes to say, not the other way around.

Output: return ONLY the spoken script text, ending with the call-to-action sentence from step 6. Nothing else, no preamble, no title, no quotes around it. Never wrap the output in any document/canvas/artifact markup such as ":::writing{{...}}" or code fences - plain spoken text only, nothing before the first word or after the last word."""


def build_scenes_system(n_scenes_hint):
    # Micro-details visuels/animation extraits d'une analyse frame-by-frame
    # (1 frame/seconde, pas juste 1 frame par beat) de 2 vraies videos finance
    # - voir video-vision/library_finance/REVIEW.md, section "Micro-details
    # visuels et d'animation". Le rendu 3D photorealiste Zack D reste
    # inchange ; ce qui change, c'est CE QUI EST MIS DANS LE PLAN (comment un
    # chiffre ou un mecanisme financier est rendu visible et litteral).
    #
    # Chaque scene porte maintenant son propre "spoken_text" (voir schema JSON
    # en bas) : la voix est generee SEPAREMENT pour chaque scene (voir main()),
    # avec sa duree reelle mesuree individuellement, plutot qu'un seul bloc
    # audio decoupe a l'aveugle - c'est ce qui permet une synchro scene/audio
    # precise (demande explicite utilisateur du 26/09, la prediction de duree
    # par nombre de mots n'etant pas fiable). n_scenes_hint est donc une
    # INDICATION approximative, pas une cible exacte a atteindre a tout prix.
    return """You are an AI visual director creating cinematic scenes in the exact visual style of viral 3D-animated YouTube Shorts, and an AI animation director writing motion prompts for an image-to-video model.

TASK: given a video script, break it into scene-by-scene prompts, in order - roughly {n_scenes_hint} scenes as a loose guide (not a hard target). Each scene must also carry the EXACT spoken_text assigned to it (verbatim substring of the script, including any [tag] present) - every word of the script must be assigned to exactly one scene, in order, with nothing skipped or duplicated. A beat is usually one sentence, but group 2 short consecutive sentences into ONE scene when they describe the same location/moment (see the final-scene note below). AVOID creating a scene whose spoken_text is only a few words (under ~4-5 words) - merge it into the adjacent scene instead, since a very short spoken line makes a wastefully short video clip.

MASCOT RULE (mandatory - this is the channel's main recurring host, critical for brand recognition): this exact character, reused word-for-word whenever he appears:
"{character}"
He MUST appear in the very FIRST scene (the hook) and the very LAST scene (the payoff+CTA) of every video, presented in a confident, knowing host-like pose - even if the script's words don't literally name him. He is the constant anchor of the channel, but he is not necessarily the only figure: OTHER human characters MAY also appear in other scenes when the story genuinely needs them (e.g. an illustrative example about "someone", a second person for a comparison, a bank teller, a shopper) - describe any such other character clearly and keep THEM consistent scene-to-scene within that one video, but never let another character replace Ferdinand as the host in the hook/closing scenes. Scenes with no character at all (a pure object/environment shot, or a diagram/evidence-board beat) are fine too.

MANDATORY STYLE LOCK - append this exact text at the end of every image_prompt:
"{style_lock}"

CAMERA ANGLES for image_prompt - pick a different one each scene, never repeat consecutively: extreme macro close-up, over-shoulder blurred foreground, through-glass framing, low ground-level wide shot, medium shot, interior tight shot, bird's-eye aerial view, slow push-in close-up.

VISIBLE NUMBERS RULE (only when the script beat actually contains a number - most beats in this format won't, and that's fine): if a scene's script beat does contain a specific number, amount, or percentage, that number should appear PHYSICALLY WRITTEN AND READABLE somewhere inside the image itself - not just implied. Put it on a photorealistic in-world prop: a price tag, a receipt, a road sign, a digital screen/monitor, a document. Do not invent a number-bearing prop for a beat that has no number in the script.

MECHANISM/REASON LITERALIZATION RULE: when a scene's beat reveals the hidden reason/mechanism behind the everyday feeling (a psychological trick, a pricing strategy, a banking mechanism, an economic principle), stage it as a literal, visual metaphor - photorealistic 3D-rendered - rather than just a character talking. Example patterns: a price tag physically changing from a round number to one ending in .99; a hand adjusting a store's shelf layout; a phone screen glowing with a notification designed to pull attention; a vault or ledger for a banking/interest mechanism; a puppet-string or magnet visual for a psychological pull. Pick whatever concrete visual best matches THIS specific mechanism - the reveal should coincide with the exact sentence that explains it in the script.

DIAGRAM / RUNNING-NUMBERS BEATS: when a beat is about numbers accumulating or a step-by-step breakdown (rather than a character action), do NOT describe a flat 2D infographic. Instead describe a photorealistic 3D "evidence board" or "war room" scene consistent with the style lock: a corkboard covered in printed documents, photos and string connections, or a glass wall/whiteboard covered in handwritten figures and taped receipts, or a holographic financial display in a dark room - something a thriller/heist movie would show a character analyzing. If a character is present in this kind of beat, keep them small in frame, in a observing/presenting stance, off to one side, so the numbers/documents stay the visual focus.

ENVIRONMENT DENSITY BY BEAT FUNCTION: for action/establishing beats (character going somewhere, doing something), the environment must be fully detailed as usual (never empty). For reaction/reveal/key-number beats, keep a real, detailed environment but rendered with shallow depth of field (background softly blurred or in shadow) so the character and the number-bearing prop stay the sharp focal point - never a flat/plain/empty background, always real depth with soft-focus context behind it.

SCENE LIVELINESS RULE (critical - this is what stops scenes from feeling like "a character posed alone in an empty-feeling room"): every single scene must feel genuinely lived-in and populated, not just a nicely-detailed but static backdrop behind one posed character. For each scene, use at least one (mix and vary across scenes, don't repeat the same technique every time):
- A concrete prop/object directly tied to what that beat is saying (a phone showing a bank app, a receipt in hand, a laptop screen with a relevant page open, hands counting cash, a specific store shelf) - read the sentence and ask "what physical thing from this can I put in frame?"
- OTHER PEOPLE in the background or midground, doing something plausible for the location (other shoppers, coworkers at other desks, passersby on a street, other customers in line) - a real space has other people in it, not just the main character alone.
- Ambient activity/life in the environment (a TV or screen playing something in the background, steam from a coffee, traffic outside a window, someone walking past in the corridor).
Never leave a scene as just the character standing/posed in a pretty-but-static space with nothing else going on.

HELD POSE RULE: describe each character pose as a single, clear, deliberately held gesture (arms crossed, hand on chin in thought, pointing, presenting stance) rather than a mid-motion or ambiguous pose - the image must read instantly as a frozen, storyboard-clear moment, not a blurred in-between frame.

FINAL SCENE (mandatory grouping): the script's last two sentences are always the PAYOFF line and a short follow/subscribe request. These two share ONE final scene together (both spoken over the same closing image/clip, and their spoken_text concatenated together) - never split them into two separate scenes.

Each image_prompt: character (if any) + specific action or held pose + at least one liveliness element from the SCENE LIVELINESS RULE + environment per the density rule above + any number/mechanism made physically visible per the rules above + camera angle + lighting (natural daylight/golden hour/indoor fluorescent/night streetlight/dramatic shadows) + mood (tense/panicked/calm/urgent/shocked) + the style lock appended at the end.

Each animation_prompt (max 50 words): camera motion and subject motion described separately, ONE dominant motion, camera essentially STATIC/LOCKED for almost every scene - real shots in this genre hold perfectly still and let hard cuts carry the energy, not movement within the shot. Only allow subtle micro-motion (breathing, a slight blink, hair or paper stirring, a light flicker) unless the scene is the tense/reveal/final beat, where a slow push-in or slight handheld shake is allowed. Never describe camera movement as the default.

Never use: "simple background", "clean background", "smooth skin", "vibrant colors", "cartoon", "Pixar", "octane render", "stylized", brand logos, "infographic", "flat design", "2D".

SOUND DESIGN RULE: each scene may carry at most ONE sound effect, chosen ONLY from this closed list:
{sfx_vocabulary}
Set "sfx" to {{{{"cue": "<key from the list>", "word": "<one word copied EXACTLY from this scene's spoken_text>"}}}} - the effect will be played on that word. Use the key exactly as written; any other value is discarded.
Leave "sfx" as null for AT LEAST HALF the scenes. A sound on every scene sounds cheap and buries the narration - restraint is what reads as a human edit. Only add one when the word genuinely evokes the sound (money, paper, a phone, a heartbeat, a revelation). Never pick a cue just to fill the field.

Output ONLY valid JSON (no markdown fences, no preamble), matching exactly:
{{{{"scenes": [{{{{"scene_no": 1, "spoken_text": "...", "medium": "real|3d_anatomical|3d_game", "camera_angle": "...", "image_prompt": "...", "animation_prompt": "...", "sfx": null}}}}]}}}}""".format(
        n_scenes_hint=n_scenes_hint, style_lock=STYLE_LOCK, character=CHARACTER,
        sfx_vocabulary=sfx.vocabulary_block() or "- (aucun son disponible)",
    )


def http_json(url, headers, body=None, method="GET"):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:500]}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # Coupure reseau / timeout socket (pas une erreur HTTP) - ne doit
        # jamais faire planter le pipeline, juste compter comme un echec
        # de cette tentative (les appelants retentent).
        print(f"  Erreur reseau ({type(e).__name__}): {e}")
        return None


def claude(system, user_text, max_tokens=2000, retries=4):
    # NOTE: Claude Sonnet 5 / Opus 5 indisponibles sur KIE.AI au moment du test
    # (erreur 530 Cloudflare, backend Anthropic injoignable). Repli temporaire
    # sur GPT-5.2 (98% de succes constate), meme role (idee/script/scenes).
    for attempt in range(1, retries + 1):
        result = http_json(
            "https://api.kie.ai/gpt-5-2/v1/chat/completions",
            {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            {
                "model": "gpt-5.2",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
            },
            method="POST",
        )
        if result:
            choices = result.get("choices", [])
            if choices:
                return choices[0]["message"]["content"]
        print(f"  (retry {attempt}/{retries} apres echec GPT-5.2)")
        time.sleep(5 * attempt)
    return None


def create_task(model, input_body, retries=3):
    for attempt in range(1, retries + 1):
        result = http_json(
            "https://api.kie.ai/api/v1/jobs/createTask",
            {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            {"model": model, "input": input_body},
            method="POST",
        )
        if result and result.get("data"):
            return result["data"]["taskId"]
        print(f"  createTask {model} -> {result}")
        print(f"  (retry {attempt}/{retries})")
        time.sleep(5 * attempt)
    return None


def wait_for_result(task_id, max_wait=600, interval=8):
    """Sonde une tache jusqu'a son resultat.

    Emet un battement de coeur regulier : sans lui, cette boucle peut rester
    muette jusqu'a 10 minutes (generation video), et cote interface on ne
    distingue plus "le modele travaille" de "tout est plante".
    """
    elapsed = 0
    last_beat = 0
    last_state = "?"
    while elapsed < max_wait:
        result = http_json(
            f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}",
            {"Authorization": f"Bearer {API_KEY}"},
        )
        if result:
            data = result.get("data", {})
            state = data.get("state")
            last_state = state or "?"
            if state == "success":
                return data
            if state == "fail":
                print(f"    ECHEC : {data.get('failMsg')}")
                return None
        else:
            last_state = "injoignable"
        time.sleep(interval)
        elapsed += interval
        if elapsed - last_beat >= 24:
            last_beat = elapsed
            print(f"    ATTENTE {elapsed}s/{max_wait}s (etat={last_state})")
    print(f"    Timeout apres {max_wait}s (dernier etat={last_state}).")
    return None


def create_and_wait(model, input_body, max_wait=300, job_retries=3):
    """create_task() ne retente que les echecs de SOUMISSION (422, reseau...).
    Mais une tache bien soumise peut aussi echouer cote serveur une fois
    lancee (state='fail', ex. "internal error, please try again later" -
    observe sur Runway le 26/09, sans lien avec le contenu de la requete) -
    wait_for_result() abandonnait alors direct. Cette fonction retente le
    cycle COMPLET (nouvelle soumission incluse) sur ce genre d'echec."""
    for attempt in range(1, job_retries + 1):
        task_id = create_task(model, input_body)
        if task_id:
            data = wait_for_result(task_id, max_wait=max_wait)
            if data:
                return data
        if attempt < job_retries:
            print(f"    (tache {model} echouee, nouvelle tentative {attempt + 1}/{job_retries})")
            time.sleep(8 * attempt)
    return None


def get_result_url(data):
    result_json = data.get("resultJson")
    if not result_json:
        return None
    urls = json.loads(result_json).get("resultUrls", [])
    return urls[0] if urls else None


def download(url, path, retries=4):
    # Contrairement a http_json, urlretrieve n'avait aucune gestion d'erreur -
    # un simple hoquet reseau (RemoteDisconnected, timeout...) faisait planter
    # tout le pipeline apres un appel API deja reussi (bug observe le 25/09,
    # en toute fin de generation voix). Retente comme les autres appels reseau.
    for attempt in range(1, retries + 1):
        try:
            urllib.request.urlretrieve(url, path)
            return True
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            print(f"  Erreur telechargement ({type(e).__name__}): {e} - (retry {attempt}/{retries})")
            time.sleep(5 * attempt)
    return False


def strip_json_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    text = text.strip()
    # Filet de securite : GPT-5.2 enveloppe parfois sa reponse dans un
    # balisage inattendu avant/apres le JSON (ex. 'CodeBlock language="json">',
    # ':::writing{...}' - meme famille de bug que sur le script, forme
    # variable, voir generate_valid_script). Plutot que de traquer chaque
    # variante, on extrait simplement le premier objet JSON complet (du
    # premier '{' au dernier '}'), peu importe ce qu'il y a autour.
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]
    return text.strip()


def generate_valid_script(script_system, user_prompt, trigger_phrase, retries=3, max_tokens=800):
    """Appelle claude() pour generer un script, nettoie les artefacts connus
    (fragment de balise orpheline, wrapper ':::writing{...}'), et VALIDE que
    le script commence bien par trigger_phrase (regle obligatoire) - sinon
    regenere plutot que de livrer un script tronque/casse. Renvoie le script
    valide, ou None apres epuisement des tentatives."""
    for attempt in range(1, retries + 1):
        candidate = claude(script_system, user_prompt, max_tokens=max_tokens)
        if not candidate:
            continue
        candidate = candidate.strip().strip('"')
        candidate = re.sub(r"^[a-z]{1,15}\]\s*", "", candidate)
        candidate = re.sub(r"^:::[a-zA-Z]+(\{[^}]*\})?\s*\n?", "", candidate)
        candidate = re.sub(r"\n?:::\s*$", "", candidate)
        candidate = candidate.strip()
        # Le hook peut legitimement commencer par une balise d'emotion avant
        # le trigger phrase (ex. "[curious] Voici pourquoi...") - on l'ignore
        # pour la validation, mais on la garde dans le script final.
        check_text = re.sub(r"^\[[a-zA-Z]+\]\s*", "", candidate)
        if check_text.lower().startswith(trigger_phrase.lower()):
            return candidate
        print(f"  (tentative {attempt}/{retries} rejetee : ne commence pas par \"{trigger_phrase}\" -> \"{candidate[:60]}...\")")
    return None


def get_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def generate_voice(text, out_path, lang="en"):
    audio_profile = "dramatic French narrator" if lang == "fr" else "dramatic narrator"
    task = create_task(
        "google/gemini-3-1-flash-tts",
        {
            "speakers": [
                {"speaker_id": "Speaker 1", "voice_name": "Zephyr", "audio_profile": audio_profile,
                 "style": "Newscaster", "pace": "Natural", "accent": "Neutral"}
            ],
            "dialogue_turns": [{"speaker_id": "Speaker 1", "text": text}],
        },
    )
    if not task:
        return False
    data = wait_for_result(task, max_wait=120)
    if not data:
        return False
    url = get_result_url(data)
    if not url:
        return False
    return download(url, out_path)


def fit_clip_to_duration(clip_path, target_duration, out_path):
    """Ajuste un clip video pour qu'il dure EXACTEMENT target_duration :
    rogne si le clip est plus long (cas courant - Runway ne genere que du 5s
    ou 10s), gele la derniere image si le clip est plus court (rare - phrase
    plus longue que le plus grand clip disponible). Reencode dans tous les
    cas pour garder des parametres uniformes (h264/yuv420p/24fps/720x1280),
    necessaires pour le concat final en -c copy."""
    clip_path, out_path = Path(clip_path), Path(out_path)
    clip_dur = get_duration(clip_path)
    if clip_dur > target_duration + 0.1:
        # Rogne a la duree cible - reencode (un simple -c copy peut couper
        # sur un mauvais keyframe et donner un resultat imprecis/casse).
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(clip_path), "-t", f"{target_duration:.2f}",
             "-r", "24", "-vf", "scale=720:1280", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-an", str(out_path)],
            check=False,
        )
    elif clip_dur < target_duration - 0.1:
        # Gele la derniere image pour combler le manque (phrase plus longue
        # que le clip - rare vu nos regles de phrases courtes).
        extra = target_duration - clip_dur + 0.1
        last_frame = OUT_DIR / "_scene_last_frame_tmp.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-sseof", "-1", "-i", str(clip_path),
             "-vframes", "1", "-q:v", "2", str(last_frame)],
            check=False,
        )
        freeze_tail = OUT_DIR / "_scene_freeze_tail_tmp.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(last_frame),
             "-t", f"{extra:.2f}", "-r", "24", "-vf", "scale=720:1280", "-pix_fmt", "yuv420p", str(freeze_tail)],
            check=False,
        )
        concat_list = OUT_DIR / "_scene_concat_tmp.txt"
        concat_list.write_text(
            f"file '{clip_path.resolve()}'\nfile '{freeze_tail.resolve()}'\n", encoding="utf-8"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(out_path)],
            check=False,
        )
    else:
        # Deja a la bonne duree (a 0.1s pres) - reencode quand meme pour
        # garantir des parametres uniformes avec les autres scenes.
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(clip_path),
             "-r", "24", "-vf", "scale=720:1280", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-an", str(out_path)],
            check=False,
        )


def sync_video_to_audio(video_path, audio_path, out_path):
    """Si l'audio final est plus long que la video (scenes a duree fixe),
    gele la derniere image le temps qu'il faut plutot que de couper la
    narration (technique validee sur le doublage FR)."""
    video_path, audio_path, out_path = Path(video_path), Path(audio_path), Path(out_path)
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path)
    if audio_dur > video_dur + 0.2:
        extra = audio_dur - video_dur + 0.5
        last_frame = OUT_DIR / "_last_frame_tmp.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-sseof", "-1", "-i", str(video_path),
             "-vframes", "1", "-q:v", "2", str(last_frame)],
            check=False,
        )
        freeze_tail = OUT_DIR / "_freeze_tail_tmp.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(last_frame),
             "-t", f"{extra:.2f}", "-r", "24", "-vf", "scale=720:1280", "-pix_fmt", "yuv420p", str(freeze_tail)],
            check=False,
        )
        concat_list2 = OUT_DIR / "_concat_extended_tmp.txt"
        concat_list2.write_text(
            f"file '{video_path.resolve()}'\nfile '{freeze_tail.resolve()}'\n", encoding="utf-8"
        )
        extended = OUT_DIR / "_concat_extended_tmp.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list2), "-c", "copy", str(extended)],
            check=False,
        )
        video_path = extended
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video_path), "-i", str(audio_path),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(out_path)],
        check=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=list(MODES.keys()), default="short",
                         help="short = histoire resserree (defaut) ; 60s = histoire complete, duree >=60s garantie")
    parser.add_argument("--lang", choices=["en", "fr"], default="en",
                         help="en = script+voix en anglais (defaut) ; fr = script+voix generes directement en francais")
    parser.add_argument("--video-model", choices=["seedance", "runway"], default="runway",
                         help="runway = runway (defaut, ~31%% moins cher a 720p, valide sur plusieurs runs) ; seedance = bytedance/seedance-1.5-pro (repli)")
    parser.add_argument("--out-dir", default=None,
                         help="Dossier de sortie (defaut: a cote du script). Utilise par le backend "
                              "pour isoler chaque job dans son propre dossier.")
    parser.add_argument("--no-subtitles", action="store_true",
                         help="Desactive les sous-titres animes incrustes (actifs par defaut).")
    parser.add_argument("--no-sfx", action="store_true",
                         help="Desactive les bruitages (actifs par defaut).")
    args = parser.parse_args()

    # Sortie non bufferisee : le backend lit la progression ligne par ligne en
    # temps reel (sans ca, Python bufferise quand stdout n'est pas un terminal
    # et rien ne s'affiche avant la fin du process).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    global OUT_DIR
    if args.out_dir:
        OUT_DIR = Path(args.out_dir)
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    mode_cfg = MODES[args.mode]
    suffix = "" if args.mode == "short" else f"_{args.mode}"
    if args.lang == "fr":
        suffix += "_fr_direct"  # suffixe distinct du doublage manuel precedent (voice_60s_fr.wav etc.)
    if args.video_model == "seedance":
        suffix += "_seedance"  # runway est desormais le defaut (pas de suffixe)
    print(f"=== Mode : {args.mode} / Langue : {args.lang} / Video : {args.video_model} ===\n")

    script_system = build_script_system(mode_cfg, lang=args.lang)
    trigger_phrase = "Voici pourquoi" if args.lang == "fr" else "Here's why"

    idea_file = OUT_DIR / f"idea{suffix}.txt"
    script_file = OUT_DIR / f"script{suffix}.txt"
    scenes_file = OUT_DIR / f"scenes_raw{suffix}.json"
    audio_path = OUT_DIR / f"voice{suffix}.wav"  # assemble a l'etape 5 a partir des voix par scene

    if idea_file.exists() and script_file.exists() and scenes_file.exists():
        print(f"=== 1-3. Reprise depuis le cache ({idea_file.name}/{script_file.name}/{scenes_file.name}) ===")
        first_idea = idea_file.read_text(encoding="utf-8").strip()
        script = script_file.read_text(encoding="utf-8").strip()
        scenes = json.loads(scenes_file.read_text(encoding="utf-8"))["scenes"]
        print(f"Idee : {first_idea}")
        print(f"Script : {script}")
        print(f"{len(scenes)} scenes.")
    else:
        print("=== 1. Generation de l'idee ===")
        ideas_text = claude(build_idea_system(args.lang), "Give me 10 ideas.", max_tokens=500)
        if not ideas_text:
            print("ECHEC total sur la generation d'idees. Arret.")
            return
        print(ideas_text)
        first_idea = None
        for line in ideas_text.splitlines():
            m = re.match(r"^\s*\d+[\.\)]\s*(.+)", line)
            if m:
                first_idea = m.group(1).strip()
                break
        if not first_idea:
            first_idea = ideas_text.splitlines()[0].strip()
        print(f"\n-> Idee choisie : {first_idea}")
        idea_file.write_text(first_idea, encoding="utf-8")

        print("\n=== 2. Generation du script ===")
        script = generate_valid_script(script_system, f"Video idea: {first_idea}", trigger_phrase)
        if not script:
            print("ECHEC : le script ne commence jamais correctement apres 3 tentatives. Arret.")
            return
        print(script)
        script_file.write_text(script, encoding="utf-8")

        # Garantie dure >= 60s pour le mode 60s (eligibilite monetisation
        # TikTok). Un appel voix de CONTROLE (pas la voix finale - celle-ci
        # sera regeneree scene par scene a l'etape 4 pour la synchro precise)
        # mesure juste la duree naturelle du script et le regenere plus
        # etoffe si besoin, avant de lancer le travail couteux par scene.
        n_scenes_hint = 8
        if args.mode == "60s":
            precheck_audio = OUT_DIR / f"_precheck{suffix}.wav"
            if not generate_voice(script, precheck_audio, lang=args.lang):
                print("ECHEC generation voix de controle. Arret.")
                return
            audio_dur = get_duration(precheck_audio)
            print(f"  Controle duree : {audio_dur:.1f}s")
            min_duration_attempt = 1
            while audio_dur < 60 and min_duration_attempt < 4:
                min_duration_attempt += 1
                print(f"  Duree {audio_dur:.1f}s < 60s cible - regeneration d'un script plus etoffe (tentative {min_duration_attempt}/4)")
                longer_prompt = (
                    f"Video idea: {first_idea}\n\n"
                    f"IMPORTANT: your previous attempt at this script was too short "
                    f"({audio_dur:.0f} seconds spoken aloud). Write a noticeably longer, "
                    f"fuller version this time - include the optional example (step 4) "
                    f"with real concrete detail, and go deeper into the hidden reason "
                    f"(step 3) with an extra sentence or two of genuine explanation. "
                    f"Do not pad with filler or repetition - add real additional substance."
                )
                candidate = generate_valid_script(script_system, longer_prompt, trigger_phrase)
                if not candidate:
                    print("  (echec de regeneration, on garde la version actuelle)")
                    break
                script = candidate
                print(script)
                script_file.write_text(script, encoding="utf-8")
                if not generate_voice(script, precheck_audio, lang=args.lang):
                    print("  (echec voix de controle sur la version etoffee, on garde la precedente)")
                    break
                audio_dur = get_duration(precheck_audio)
                print(f"  Nouvelle duree : {audio_dur:.1f}s")
            if audio_dur < 60:
                print(f"  ATTENTION : toujours sous 60s ({audio_dur:.1f}s) apres {min_duration_attempt} tentative(s) - on continue quand meme.")
            n_scenes_hint = max(8, min(20, round(audio_dur / SCENE_CLIP_SECONDS)))
        print(f"  -> ~{n_scenes_hint} scenes visees (indicatif ; la duree de chaque scene sera mesuree individuellement a l'etape 4)")

        print("\n=== 3. Decoupage en scenes (avec texte parle par scene) ===")
        scenes_system = build_scenes_system(n_scenes_hint)
        scenes_raw = claude(scenes_system, f"Script:\n{script}", max_tokens=6000)
        if not scenes_raw:
            print("ECHEC total sur le decoupage en scenes. Arret.")
            return
        scenes_raw = strip_json_fences(scenes_raw)
        scenes_file.write_text(scenes_raw, encoding="utf-8")
        scenes = json.loads(scenes_raw)["scenes"]
        print(f"{len(scenes)} scenes generees.")
        for s in scenes:
            print(f"  [{s['scene_no']}] {s['camera_angle']}: {s.get('spoken_text', '')[:50]!r} | {s['image_prompt'][:60]}...")

    n_scenes = len(scenes)
    clip_paths = []
    audio_seg_paths = []
    # (numero, texte parle, duree mesuree, bruitage) - sert aux sous-titres et
    # aux bruitages. Alimente uniquement quand la scene aboutit : une scene
    # ratee ne doit pas y figurer, sinon tout ce qui suit est decale.
    sub_segments = []
    scenes_dir = OUT_DIR / f"scenes{suffix}"
    scenes_dir.mkdir(exist_ok=True)

    print("\n=== 4. Generation scene par scene (voix individuelle + image + video calee sur sa duree) ===")
    for s in scenes:
        n = s["scene_no"]
        clip_path = scenes_dir / f"scene_{n:02d}.mp4"
        seg_audio_path = scenes_dir / f"scene_{n:02d}.wav"
        if clip_path.exists() and seg_audio_path.exists():
            print(f"\n=== Scene {n}/{n_scenes} : deja generee, on reutilise ===")
            clip_paths.append((n, clip_path))
            audio_seg_paths.append((n, seg_audio_path))
            # La duree est relue sur le fichier : sur une reprise, la voix n'a
            # pas ete regeneree, donc seg_dur n'existe pas dans ce tour.
            sub_segments.append(
                (n, s.get("spoken_text", ""), get_duration(seg_audio_path), s.get("sfx"))
            )
            continue

        spoken_text = s.get("spoken_text", "").strip()
        if not spoken_text:
            print(f"\n=== Scene {n}/{n_scenes} : ATTENTION spoken_text vide, scene ignoree ===")
            continue

        print(f"\n=== Scene {n}/{n_scenes} : voix ===")
        if not generate_voice(spoken_text, seg_audio_path, lang=args.lang):
            print("  Echec voix de la scene.")
            continue
        seg_dur = get_duration(seg_audio_path)
        print(f"  Voix OK ({seg_dur:.2f}s) : {spoken_text[:60]!r}")

        print(f"=== Scene {n}/{n_scenes} : image ===")
        img_data = create_and_wait(
            "google/nano-banana",
            {"prompt": s["image_prompt"], "image_size": "9:16", "output_format": "png"},
            max_wait=180,
        )
        if not img_data:
            print("  Echec generation image.")
            continue
        img_url = get_result_url(img_data)
        print(f"  Image OK : {img_url}")

        print(f"=== Scene {n}/{n_scenes} : video ({args.video_model}) ===")
        # Toujours demander le preset "5" a Runway : le preset "10" s'est
        # revele peu fiable en test (26/09 - les 4 echecs "internal error"
        # d'un run correspondaient exactement aux 4 scenes qui avaient
        # demande du 10s, les scenes en 5s sont toutes passees). Pour une
        # voix plus longue que 5s, fit_clip_to_duration comblera le manque
        # en gelant la derniere image plutot que de risquer l'echec du 10s.
        if args.video_model == "runway":
            vid_data = create_and_wait(
                "runway",
                {
                    "prompt": s["animation_prompt"],
                    "image_url": img_url,
                    "duration": "5",
                    "quality": "720p",
                    "aspect_ratio": "9:16",
                    "watermark": "",
                },
                max_wait=300,
            )
        else:
            vid_data = create_and_wait(
                "bytedance/seedance-1.5-pro",
                {
                    "prompt": s["animation_prompt"],
                    "input_urls": [img_url],
                    "aspect_ratio": "9:16",
                    "resolution": "720p",
                    "duration": 5,
                    "fixed_lens": False,
                    "generate_audio": False,
                },
                max_wait=300,
            )
        if not vid_data:
            print("  Echec generation video.")
            continue
        vid_url = get_result_url(vid_data)
        raw_clip_path = scenes_dir / f"scene_{n:02d}_raw.mp4"
        if not download(vid_url, raw_clip_path):
            print("  Echec telechargement video.")
            continue
        fit_clip_to_duration(raw_clip_path, seg_dur, clip_path)
        print(f"  Video OK -> {clip_path} (calee sur {seg_dur:.2f}s)")
        clip_paths.append((n, clip_path))
        audio_seg_paths.append((n, seg_audio_path))
        sub_segments.append((n, spoken_text, seg_dur, s.get("sfx")))

    print("\n=== 5. Montage FFmpeg ===")
    clip_paths.sort(key=lambda x: x[0])
    audio_seg_paths.sort(key=lambda x: x[0])
    if not clip_paths:
        print("Aucun clip genere, arret.")
        return

    concat_list = OUT_DIR / f"concat{suffix}.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve()}'" for _, p in clip_paths), encoding="utf-8"
    )
    concat_video = OUT_DIR / f"concat{suffix}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat_list), "-c", "copy", str(concat_video)],
        check=False,
    )
    print(f"  Concat video OK -> {concat_video}")

    audio_concat_list = OUT_DIR / f"concat_audio{suffix}.txt"
    audio_concat_list.write_text(
        "\n".join(f"file '{p.resolve()}'" for _, p in audio_seg_paths), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(audio_concat_list), "-c", "copy", str(audio_path)],
        check=False,
    )
    print(f"  Concat audio OK -> {audio_path}")

    # --- Sous-titres incrustes ------------------------------------------
    # A faire AVANT la fusion audio : sync_video_to_audio copie le flux video
    # tel quel (-c:v copy), il n'y aurait plus d'occasion de les incruster.
    sub_segments.sort(key=lambda x: x[0])
    timeline_segments = [(text, dur) for _, text, dur, _ in sub_segments]

    if not args.no_subtitles:
        print("  Sous-titres...")
        ass_path = OUT_DIR / f"subs{suffix}.ass"
        n_lines = subtitles.build_ass(timeline_segments, ass_path)
        if n_lines:
            burned = OUT_DIR / f"concat_subs{suffix}.mp4"
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(concat_video),
                 "-vf", subtitles.ass_filter(ass_path),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-an", str(burned)],
                check=False,
            )
            if result.returncode == 0 and burned.exists():
                concat_video = burned
                print(f"  Sous-titres OK ({n_lines} mots) -> {burned}")
            else:
                # Non bloquant : une video sans sous-titres reste utilisable,
                # perdre 30 minutes de generation pour ca ne le serait pas.
                print("  ATTENTION : incrustation des sous-titres echouee, on continue sans.")
        else:
            print("  (aucun texte a sous-titrer)")

    # --- Bruitages -------------------------------------------------------
    # Melanges dans l'AUDIO, avant la fusion : la video n'est pas touchee,
    # donc sync_video_to_audio peut continuer a la copier sans reencoder.
    if not args.no_sfx and audio_path.exists():
        print("  Bruitages...")
        placed, warnings = sfx.plan(
            timeline_segments, [cue for _, _, _, cue in sub_segments]
        )
        for w in warnings:
            print(f"    ATTENTION : {w}")
        if placed:
            mixed = OUT_DIR / f"voice_sfx{suffix}.wav"
            if sfx.mix_into_audio(audio_path, placed, mixed):
                audio_path = mixed
                print(f"  Bruitages OK ({len(placed)} poses)")
            else:
                # Non bloquant, comme les sous-titres : une video sans
                # bruitages reste utilisable, perdre la generation non.
                print("  ATTENTION : mixage des bruitages echoue, on continue sans.")
        else:
            print("  (aucun bruitage retenu)")

    final_video = OUT_DIR / f"final{suffix}.mp4"
    if audio_path.exists():
        # Chaque clip est deja cale sur sa propre voix a l'etape 4 - l'ecart
        # residuel ici est juste l'arrondi d'encodage (dixiemes de seconde),
        # plus un vrai decalage de plusieurs secondes comme avant.
        sync_video_to_audio(concat_video, audio_path, final_video)
        print(f"  Fusion audio OK -> {final_video}")
    else:
        final_video = concat_video
        print("  Pas d'audio, video finale = concat seule.")

    print(f"\n=== TERMINE : {final_video} ===")


if __name__ == "__main__":
    main()
