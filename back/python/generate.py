"""
Pipeline complet : genere une video "Pourquoi... ?" de bout en bout
(finance / psychologie de l'argent, rendu 3D photorealiste style Zack D
Films, mascotte recurrente Ferdinand la taupe), via KIE.AI (GPT-5.2, nano-banana,
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
import random
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import http.client
from pathlib import Path

import ai_metadata
import sfx
import styles
import subtitles
import synthid_remove
import variation
import watermark


_API_KEY = None


def api_key():
    """Cle API KIE.AI. Priorite a la variable d'environnement (indispensable
    pour l'hebergement : pas de chemin absolu Windows en dur), avec repli sur
    un fichier local pour l'usage en developpement.

    Lue A LA DEMANDE, pas a l'import : au niveau module, l'absence de cle
    tuait le script avant meme argparse (`--help` inclus) et, pour
    graphique.py qui importe ce module en cours de route, l'erreur ne
    survenait qu'apres le chargement des donnees.
    """
    global _API_KEY
    if _API_KEY:
        return _API_KEY
    env_key = os.environ.get("KIE_API_KEY")
    if env_key:
        _API_KEY = env_key.strip().split(":")[-1].strip()
        return _API_KEY
    for candidate in (
        Path(__file__).parent / "api.txt",
        Path(r"F:\Tiktok\api.txt"),
    ):
        if candidate.exists():
            _API_KEY = candidate.read_text(encoding="utf-8").strip().split(":")[-1].strip()
            return _API_KEY
    raise SystemExit(
        "Cle API introuvable : definis la variable d'environnement KIE_API_KEY "
        "ou place un fichier api.txt a cote de ce script."
    )


# OUT_DIR est fixe par --out-dir (chaque job du backend ecrit dans son propre
# dossier) ; par defaut, a cote du script comme avant en usage CLI direct.
OUT_DIR = Path(__file__).parent

# Dossier de cache des scenes, commun a toutes les tentatives d'UN MEME sujet
# (--cache-dir). Confondu avec OUT_DIR, il etait recree vierge a chaque
# lancement : la reprise annoncee apres un echec ne pouvait pas avoir lieu.
CACHE_DIR = None

SCENE_CLIP_SECONDS = 5  # duree fixe par scene (Seedance/Runway)

# Resolution de sortie, choisie par --quality. UNE seule source de verite :
# la valeur demandee aux modeles et celle imposee aux segments reencodes
# doivent concorder, sinon le concat final (-c copy) refuse de coller des
# segments de tailles differentes.
# Les sous-titres et le filigrane n'ont pas a y etre adaptes : leurs fichiers
# ASS declarent un canevas 720x1280 que libass met a l'echelle tout seul, et
# les deux resolutions ont le meme rapport 9:16.
RESOLUTIONS = {"720p": (720, 1280), "1080p": (1080, 1920)}
VIDEO_QUALITY = "720p"  # envoye a Runway ("quality") et Seedance ("resolution")
VIDEO_WIDTH, VIDEO_HEIGHT = RESOLUTIONS[VIDEO_QUALITY]
VIDEO_SCALE = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}"

# Qualite des clips INTERMEDIAIRES (calage sur la voix). Plus fine que celle
# de la passe finale a dessein : les pertes se cumulent, et ce qu'un premier
# encodage ecrase ne revient pas. Sans ce reglage, libx264 appliquait son
# defaut (crf 23) juste apres le telechargement - donc une compression plus
# agressive que la passe sous-titres (crf 20) qui suit, ce qui gachait une
# partie de la resolution payee au fournisseur. Les fichiers grossissent,
# mais ils sont purges des que le job reussit.
CLIP_CRF = "18"

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
        "words_hint": "roughly 145-175 words as a rough feel for length - NOT a hard limit, just a guide for a fuller explanation. This range is measured on a real finished video, not guessed: the voice used here delivers about 120 words per minute, so 145 words lands near 72 seconds and 175 near 87 seconds - comfortably over the 60-second threshold without dragging. Going much past 175 words makes the video overlong, not richer. Spend the room on step 4 - more arithmetic steps, not more adjectives.",
    },
}

# Conserve pour compatibilite : la source de verite du rendu vit desormais
# dans styles.py, qui porte DEUX familles completes (3D et collage papier).
STYLE_LOCK = styles.FERDINAND["style_lock"]

# Mascotte recurrente de la chaine (demande explicite utilisateur, en
# remplacement de Picsou/Scrooge McDuck - meme esprit "riche et malin" mais
# design 100% original, aucun probleme de droits d'auteur). Description FIXE
# reutilisee mot pour mot sur TOUTES les videos (pas juste au sein d'une
# meme video) pour construire une identite de marque reconnaissable.
CHARACTER = (
    "Ferdinand, an anthropomorphic European mole standing and posing like a "
    "human, dense velvety fur in warm dark sepia-brown (never flat black, "
    "never grey), a pale pink pointed snout and large pale pink shovel-shaped "
    "front paws, small round brass spectacles, wearing a tailored deep-red "
    "three-piece suit with a gold pocket-watch chain and a black silk pocket "
    "square, confident bourgeois posture, no logos"
)

# NICHE : finance / investissement / economie / psychologie de l'argent.
# Format "VOICI POURQUOI" (pivot demande explicitement par l'utilisateur, qui
# a fourni sa propre liste de ~80 titres comme reference - voir conversation
# du 25/09). Chaque video part d'une sensation/observation ultra-banale sur
# l'argent que tout le monde a deja vecue, et revele la raison cachee
# derriere. Ce n'est PLUS le format "Tom accumule des chiffres" d'avant -
# beaucoup de ces sujets sont des mecanismes psychologiques/commerciaux qui
# n'ont pas besoin d'une histoire chiffree pour etre clairs.

# Tout ce qui depend de la langue, en un seul endroit. C'etait auparavant un
# binaire fr/en dissemine dans six fonctions : ajouter une langue obligeait a
# retrouver chaque `if lang == "fr"`, et en oublier un passait inapercu.
LANGUAGES = {
    "en": {
        "trigger": "Why",
        "name": "English",
        "audio_profile": "dramatic narrator",
        "suffix": "",
    },
    "fr": {
        "trigger": "Pourquoi",
        "name": "French",
        "audio_profile": "dramatic French narrator",
        # Suffixe historique : distingue du doublage manuel d'avant la voix
        # generee scene par scene (voice_60s_fr.wav).
        "suffix": "_fr_direct",
    },
    "de": {
        "trigger": "Warum",
        "name": "German",
        "audio_profile": "dramatic German narrator",
        "suffix": "_de",
        # Le marche compte pour CHAQUE video, pas seulement celles dont le
        # sujet est explicitement local : un mecanisme universel raconte avec
        # des dollars et un decor americain ne parle a personne en Allemagne.
        "script_context": (
            "AUDIENCE: German viewers in Germany. Every amount is in euros and realistic "
            "for Germany (a typical net salary around 2000-2800 EUR, rent as the biggest "
            "monthly item, overdraft interest above 10 percent). When an institution or a "
            "shop makes the point concrete, use one Germans actually deal with - Sparkasse "
            "or Hausbank, Krankenkasse, Finanzamt, Schufa, Rundfunkbeitrag, Aldi, Lidl, "
            "Rewe, dm - rather than a generic or American one. Everyday references should "
            "feel German: Pfand on bottles, Doener prices, Kleingeld, Nebenkosten. "
            "Address the viewer informally as 'du', never 'Sie'. Never mention dollars, "
            "American institutions, or US-specific habits."
        ),
        "visual_context": (
            "SETTING: every scene takes place in Germany or continental Europe. Money on "
            "screen is euro notes and coins, never dollars. Streets, shops, flats and "
            "offices look German: older apartment buildings with tall windows, tiled "
            "supermarket floors with narrow aisles, bicycles, "
            "regional trains. Never American suburbs, strip malls, yellow school buses or "
            "dollar bills. Real shop and brand signage stays unreadable or absent - never reproduce an existing company's name or logo. This does NOT forbid the video's own headline cards and numbers, which follow the style rules above."
        ),
    },
}


def lang_cfg(lang):
    return LANGUAGES.get(lang, LANGUAGES["en"])


def _used_ideas_file():
    """Memoire des titres deja produits, PARTAGEE entre les jobs.

    OUT_DIR est propre a chaque job (DATA_DIR/jobs/<id>) : y ranger cet
    historique ne servirait a rien. Le dossier parent, lui, est commun.
    """
    return OUT_DIR.parent / "_used_ideas.txt"


def load_used_ideas():
    try:
        path = _used_ideas_file()
        if not path.exists():
            return set()
        return {l.strip().lower() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
    except OSError:
        return set()  # jamais bloquant : au pire on risque un doublon


def remember_idea(idea):
    try:
        with _used_ideas_file().open("a", encoding="utf-8") as f:
            f.write(idea.strip() + "\n")
    except OSError:
        pass


def build_idea_system(lang="en"):
    cfg = lang_cfg(lang)
    trigger_phrase = cfg["trigger"]
    # Seule la phrase d'accroche etait traduite : le modele enchainait donc en
    # anglais apres l'accroche, produisant des titres bilingues.
    lang_rule = (
        f"LANGUAGE: write the ENTIRE title in natural spoken {cfg['name']} - the whole "
        "sentence, not only the opening phrase. Never mix English words in."
    )
    return f"""You are a YouTube Shorts idea strategist for a French-style finance/money-psychology channel with one strong, recognizable format: every single title is a QUESTION starting with "{trigger_phrase}" about an everyday money situation the viewer personally pays for or lives through - the video then has Ferdinand the mole dig underneath it and uncover the real mechanism, in numbers.

TASK: Generate 10 video titles, each starting with "{trigger_phrase}" and ending with a question mark.

{lang_rule}

THE PATTERN (critical): the title is a question about something concrete the viewer actually pays for, signs, or does - never an abstract topic name, never a distant political or societal scandal. Shape only: "{trigger_phrase} <concrete everyday thing the viewer pays for>?". Fill that placeholder yourself - any literal example written in this prompt is a FORBIDDEN output, never a suggestion to copy. The strongest titles contain a small built-in paradox the viewer cannot resolve alone (something that is free yet costs, cheap yet expensive, optional yet unavoidable), because that is what makes them need the answer. The video's job is to reveal the hidden mechanism (psychological, pricing, banking, contractual or tax) behind it, with real arithmetic.

Rotate across these angles (do not use the same angle for all 10 - spread across at least 5 of them):
1. Everyday money & life - common money frustrations (spending, saving, feeling broke, prices feeling higher)
2. Consumption psychology - pricing tricks, promotions, store/app design that makes you spend
3. Brain & money - cognitive biases (loss aversion, instant gratification, social proof, stress spending)
4. Banks & credit - how loans, interest, overdrafts, and installment payments really work
5. Internet & tech - the attention economy, why apps are "free", data, subscriptions
6. Work & wealth - salary vs wealth, assets vs income, why income alone isn't wealth
7. Strong curiosity - sharply counterintuitive money facts
8. Local everyday life (only when it fits naturally, do not force every video here) - local prices, local currency, local everyday scenes

Requirements: understood instantly in under 1 second, makes the viewer realise this is happening to them RIGHT NOW, highly visual, and answerable with honest arithmetic - never a question whose answer would need invented statistics.
Avoid: generic personal-finance advice ("save more", "budget better"), abstract institutional topics with no personal relatable angle, long titles.
Title rules: the full question stays under 12 words, casual spoken language, ends with a question mark, no explanations, no jargon.

Output: return ONLY the 10 titles, one per line, numbered 1 to 10, spanning at least 5 different angles above. Nothing else, no preamble."""

def build_script_system(mode_cfg, lang="en", charpente=None):
    # Format "VOICI POURQUOI" (voir build_idea_system) - explication d'une
    # sensation/observation quotidienne sur l'argent, PAS une histoire
    # chiffree a la "Tom accumule des gains". Les chiffres restent utiles
    # comme illustration ponctuelle, mais ne sont plus le moteur du script -
    # feedback explicite : l'ancienne version etait "trop dans les nombres".
    cfg = lang_cfg(lang)
    # Chemin entre l'accroche et la chute. Une seule forme existait, donc
    # chaque script de la chaine suivait rigoureusement le meme trajet.
    charpente = charpente or variation.CHARPENTES[0][1]
    trigger_phrase = cfg["trigger"]
    lang_instruction = ""
    if lang != "en":
        name = cfg["name"]
        lang_instruction = f"""
LANGUAGE (critical): the video idea given to you may be phrased in English - that's fine, translate the concept naturally. But write your ENTIRE output script in {name.upper()}, not English. Natural, spoken, everyday {name} - not a literal word-for-word translation style. The SIMPLE VOCABULARY RULE below still applies in {name} (simple everyday {name} words a teenager understands, technical terms explained in plain {name}).
"""
    if cfg.get("script_context"):
        lang_instruction += "\n" + cfg["script_context"] + "\n"
    if lang == "de":
        lang_instruction += """
GERMAN COMPOUND RULE: prefer short everyday words over long compound nouns. Say "die Kosten fuer Wohnen" rather than "Lebenshaltungskosten", "die Beitraege zur Krankenkasse" rather than "Krankenversicherungsbeitraege". Very long compounds are hard to read as burned-in subtitles and slow the viewer down. Never build a compound longer than about 20 letters when a simple phrase says the same thing.
"""
    return f"""You are a YouTube Shorts scriptwriter for a French-style finance/money-psychology channel built around one recognizable format: a "{trigger_phrase} ...?" question about an everyday money situation, answered as a short fable in which Ferdinand the mole digs underneath it and uncovers the real mechanism, in numbers.
{lang_instruction}
TASK: Write a script for the video idea the user gives you (a "{trigger_phrase}..." title).

CORE TECHNIQUE - this is a FABLE, not a lecture. Follow it precisely:
Ferdinand the mole is the one living the scene. He faces the same ordinary money situation the viewer faces, everyone around him accepts the obvious explanation, and he does the one thing moles do: he digs underneath it. He is NOT the one profiting from the trick - he is the one who uncovers it and shows it to the viewer. Tell it in the third person ("the mole"), present tense, and let the mechanism come out through what he FINDS, never through a lecture. The viewer should be following a story, not receiving a lesson.

Follow this structure:
1. HOOK (1 sentence, mandatory, opens the script verbatim as the video's title): the exact question from the chosen title, starting with "{trigger_phrase}" and ending with a question mark - reuse that title word for word, never an example written in this prompt.
2. WHAT EVERYONE SEES (1-2 sentences): the obvious, reasonable reading of the situation - the one almost everyone accepts without looking further. State it plainly, without irony.
3. THE MOLE DIGS (1-2 sentences): the mole does not accept it. He looks underneath - at the contract, the small print, the real numbers - and finds something. End this block on a short attention line that tells the viewer to pay attention now.
{charpente}
5. WHY NOBODY NOTICES (1-2 sentences): say plainly why this stays invisible - it is too small to feel, too boring to check, or buried where nobody reads. This is what makes the viewer feel the trick was aimed at them.
6. ANTITHESIS CLOSE (exactly 2 short sentences, mandatory, this is the channel's signature): two opposed sentences built the same way - what ordinary people see, then what the mole sees. Example of the SHAPE only, never the content: "Most people see a monthly fee. The mole sees a year of free money for the bank." Keep both sentences short, parallel and punchy. This is the line the viewer should repeat to someone else.
7. CALL TO ACTION (mandatory, exactly 1 short sentence, always last): unlike generic Shorts, this niche's viewers respond to a warm, personal, low-hype ask to follow/subscribe - never a generic "smash that subscribe button" line. Always start with a short "if you enjoyed/liked this" conditional clause, then the effort/behind-the-scenes ask: mention the real work behind making the video and ask for a follow in return (e.g. "If you enjoyed this, following means a lot - these videos take hours to make."). Vary the exact wording each time (never reuse the same sentence twice) but always keep both parts: the "if you liked it" clause AND the effort ask - never switch to a "more content" pitch or any other angle. Keep it under 15 words, warm and humble in tone, not salesy or hyped.

NUMBERS RULE (critical - the numbers ARE the video, read carefully): step 4 must carry real arithmetic the viewer can follow in their head, not a vague claim. Every figure has to be realistic and checkable for the audience - a plausible price, a plausible rate, a plausible monthly cost - and the amounts must actually add up when stated one after another. Prefer one concrete amount tracked all the way through over several unrelated figures. Never invent a precise-sounding statistic about a country, a market or "studies" - the only numbers allowed are the ones inside the mole's own situation. If you cannot make the arithmetic honest and simple, choose a simpler angle rather than faking precision.

SIMPLE VOCABULARY RULE (critical - a 13-year-old with no finance background must understand every sentence on first listen):
- Use only everyday, common words. Write the way you'd explain it out loud to a teenager, not the way a bank or a news article would write it.
- Never use a financial/legal/technical term without immediately explaining what it means in plain words, in the same breath. Do not assume the viewer knows what "securities", "assets", "liquidity", "equity", "amortization", "estate", "trust", "regulator", "collateral", etc. mean - either replace them with a plain-language equivalent, or add a short plain-language clarification right after the term (e.g. instead of "the bank sells securities" say "the bank sells stocks and bonds it owns" or "the bank sells investments it owns"; instead of "pledges eligible assets" say "hands over valuable stuff as a guarantee").
- THE MECHANISM (step 4) is the one place a real technical/legal term is allowed and expected (that's the "aha" fact being taught) - but even there, immediately follow it with one plain-word explanation of what it actually means in practice.
- Prefer short concrete nouns over abstract ones (say "the money" not "the capital", say "a company" not "an entity", say "borrows money" not "secures financing").
- If a sentence needs a teenager to have heard the word before to understand it, rewrite the sentence.

AUDIO DELIVERY TAGS (the voice engine supports these - use them, but sparingly): you may insert short bracketed delivery tags right before the words they should affect, e.g. [whispers], [shouting], [urgency], [confidently], [curious], [enthusiastic]. Use ONLY 2 to 4 of them in the whole script, placed only at genuine emotional turning points - never on every sentence, never more than one per sentence. Suggested placements (skip any that don't fit naturally):
- HOOK: a curiosity tag like [curious] or [intriguing] on the opening "{trigger_phrase}..." line.
- THE MOLE DIGS (step 3): [whispers] or [confidently] works well on the moment he finds what is underneath.
- ANTITHESIS CLOSE: a [dramatic] tag on the first of the two closing sentences.
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


# Mot qui identifie l'espece du personnage. Doit figurer dans CHARACTER :
# c'est lui qu'on verifie scene par scene.
ESPECE = "mole"


def _utilisable(chemin):
    """Fichier present ET non vide. Un fichier de 0 octet est le residu d'une
    ecriture interrompue : il doit etre regenere, pas repris."""
    try:
        return chemin.stat().st_size > 0
    except OSError:
        return False


def reparer_personnage(scenes):
    """Reinjecte la description complete du personnage dans les scenes ou le
    modele l'a abregee.

    Mesure sur un vrai run (03/10) : a partir de la scene 8, GPT-5.2 cesse de
    repeter la description et ecrit "Ferdinand, exact recurring appearance".
    Or le modele d'IMAGE n'a AUCUNE memoire d'une scene a l'autre - chaque
    prompt part de zero. Prive du mot "taupe", il inventait un animal au
    hasard : berger allemand, chat, loup, ours, et meme un renard. Six scenes
    correctes sur dix-sept.

    Le bug existait deja avec le renard mais restait invisible : quand le
    modele devinait "animal anthropomorphe en costume", il tombait souvent
    juste. Changer d'espece l'a revele.

    Renvoie le nombre de scenes reparees.
    """
    repares = 0
    for s in scenes:
        p = s.get("image_prompt", "")
        if "ferdinand" not in p.lower() or ESPECE in p.lower():
            continue
        # "Ferdinand, exact recurring appearance," -> description complete
        repare = re.sub(
            r"Ferdinand\s*,\s*[^,.]{0,70}?appearance\s*,?", CHARACTER + ",", p, count=1,
            flags=re.IGNORECASE,
        )
        if repare == p:  # autre forme d'abreviation : on remplace le prenom seul
            repare = re.sub(r"\bFerdinand\b", CHARACTER, p, count=1)
        s["image_prompt"] = repare
        repares += 1
    if repares:
        print(f"  ({repares} scene(s) ou la description du personnage etait abregee - reinjectee)")
    return repares


def build_scenes_system(n_scenes_hint, lang="en", ambiance=None, style=None):
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
    #
    # Les blocs qui dependent du STYLE (role, regles de mise en scene, regle
    # d'animation, interdits) viennent de styles.py : le collage papier ne se
    # contente pas d'un autre style_lock, il inverse plusieurs de ces regles -
    # notamment la camera, fixe en 3D et mobile en collage.
    cfg_style = style or styles.get(styles.DEFAUT)
    return """{role}

TASK: given a video script, break it into scene-by-scene prompts, in order - roughly {n_scenes_hint} scenes as a loose guide (not a hard target). Each scene must also carry the EXACT spoken_text assigned to it (verbatim substring of the script, including any [tag] present) - every word of the script must be assigned to exactly one scene, in order, with nothing skipped or duplicated. A beat is usually one sentence, but group 2 short consecutive sentences into ONE scene when they describe the same location/moment (see the final-scene note below). AVOID creating a scene whose spoken_text is only a few words (under ~4-5 words) - merge it into the adjacent scene instead, since a very short spoken line makes a wastefully short video clip.

MASCOT RULE (mandatory - this is the channel's main recurring host, critical for brand recognition): this exact character, whose FULL description below must be copied word-for-word into EVERY image_prompt where he appears:
"{character}"
NEVER abbreviate him. The image model generates each scene independently and has NO memory of the other scenes, so a shorthand like "Ferdinand, exact recurring appearance", "the same mole as before" or "as previously described" tells it nothing at all - it will invent a random animal instead (measured on a real run: a dog, a cat, a wolf and a bear all appeared in one video). If he is in the scene, the whole description goes in, every single time, even for the fifteenth scene in a row.
He MUST appear in the very FIRST scene (the hook) and the very LAST scene (the payoff+CTA) of every video, presented in a confident, knowing host-like pose - even if the script's words don't literally name him. He is the constant anchor of the channel, but he is not necessarily the only figure: OTHER human characters MAY also appear in other scenes when the story genuinely needs them (e.g. an illustrative example about "someone", a second person for a comparison, a bank teller, a shopper) - describe any such other character clearly and keep THEM consistent scene-to-scene within that one video, but never let another character replace Ferdinand as the host in the hook/closing scenes. Scenes with no character at all (a pure object/environment shot, or a diagram/evidence-board beat) are fine too.
{note_personnage}

MANDATORY STYLE LOCK - append this exact text at the end of every image_prompt:
"{style_lock}"

CAMERA ANGLES for image_prompt - pick a different one each scene, never repeat consecutively: extreme macro close-up, over-shoulder blurred foreground, through-glass framing, low ground-level wide shot, medium shot, interior tight shot, bird's-eye aerial view, slow push-in close-up.

VISIBLE NUMBERS RULE (only when the script beat actually contains a number - most beats in this format won't, and that's fine): if a scene's script beat does contain a specific number, amount, or percentage, that number should appear PHYSICALLY WRITTEN AND READABLE somewhere inside the image itself - not just implied. Put it on a photorealistic in-world prop: a price tag, a receipt, a road sign, a digital screen/monitor, a document. Do not invent a number-bearing prop for a beat that has no number in the script.

ON-SCREEN TEXT LANGUAGE (critical for a non-English market): every word that appears INSIDE the image - on a price tag, a headline card, a sign, a screen, a receipt - must be written in {lang_name}, never in English. A German video showing "75% OFF" instead of "75% RABATT" reads instantly as foreign, recycled content. Keep such wording to one or two common, correctly spelled words; when unsure of the spelling, describe a number alone rather than a word.

{regle_mecanisme}

{regle_diagramme}

ENVIRONMENT DENSITY BY BEAT FUNCTION: for action/establishing beats (character going somewhere, doing something), the environment must be fully detailed as usual (never empty). For reaction/reveal/key-number beats, keep a real, detailed environment but rendered with shallow depth of field (background softly blurred or in shadow) so the character and the number-bearing prop stay the sharp focal point - never a flat/plain/empty background, always real depth with soft-focus context behind it.

{regle_vivacite}

HELD POSE RULE: describe each character pose as a single, clear, deliberately held gesture (arms crossed, hand on chin in thought, pointing, presenting stance) rather than a mid-motion or ambiguous pose - the image must read instantly as a frozen, storyboard-clear moment, not a blurred in-between frame.

FINAL SCENE (mandatory grouping): the script's last sentences are always the two-sentence ANTITHESIS CLOSE and a short follow/subscribe request. These two share ONE final scene together (both spoken over the same closing image/clip, and their spoken_text concatenated together) - never split them into two separate scenes.

Each image_prompt: character (if any) + specific action or held pose + at least one liveliness element from the SCENE LIVELINESS RULE + environment per the density rule above + any number/mechanism made physically visible per the rules above + camera angle + lighting (natural daylight/golden hour/indoor fluorescent/night streetlight/dramatic shadows) + mood (tense/panicked/calm/urgent/shocked) + the style lock appended at the end.

{regle_animation}

{visual_context}

{interdits}

SOUND DESIGN RULE: each scene may carry at most ONE sound effect, chosen ONLY from this closed list:
{sfx_vocabulary}
Set "sfx" to {{{{"cue": "<key from the list>", "word": "<one word copied EXACTLY from this scene's spoken_text>"}}}} - the effect will be played on that word. Use the key exactly as written; any other value is discarded.
Aim to give EVERY scene a sound effect when one genuinely fits - a word that evokes money, paper, a phone, a heartbeat, a door, a revelation. Set "sfx" to null only when no key in the list honestly matches anything said in that scene; an absent sound is far better than a forced one. Never stretch a key to fill the field, and never repeat the same key in two consecutive scenes.

Output ONLY valid JSON (no markdown fences, no preamble), matching exactly:
{{{{"scenes": [{{{{"scene_no": 1, "spoken_text": "...", "medium": "real|3d_anatomical|3d_game", "camera_angle": "...", "image_prompt": "...", "animation_prompt": "...", "sfx": null}}}}]}}}}""".format(
        n_scenes_hint=n_scenes_hint,
        # L'ambiance s'ajoute au medium sans le remplacer : le rendu et le
        # personnage restent identiques, seul le fond/la lumiere change.
        style_lock=cfg_style["style_lock"] + (f", {ambiance}" if ambiance else ""),
        character=CHARACTER,
        role=cfg_style["role"],
        note_personnage=cfg_style["note_personnage"],
        regle_mecanisme=cfg_style["regle_mecanisme"],
        regle_diagramme=cfg_style["regle_diagramme"],
        regle_vivacite=cfg_style["regle_vivacite"],
        regle_animation=cfg_style["regle_animation"],
        interdits=cfg_style["interdits"],
        sfx_vocabulary=sfx.vocabulary_block() or "- (aucun son disponible)",
        visual_context=lang_cfg(lang).get("visual_context", ""),
        lang_name=lang_cfg(lang)["name"],
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
            {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
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
            {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
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
            {"Authorization": f"Bearer {api_key()}"},
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


def televerser(chemin):
    """Envoie un fichier local chez KIE et renvoie son URL publique.

    Necessaire parce que nano-banana-edit attend des URL dans `image_urls`,
    jamais un fichier. Les fichiers televerses sont supprimes au bout de 24h :
    la planche de style est donc renvoyee a chaque generation, ce qui coute un
    appel de quelques kilo-octets.

    Renvoie None en cas d'echec - l'appelant retombe alors sur la generation
    d'image sans reference, ce qui donne un rendu moins tenu mais une video
    quand meme.
    """
    import mimetypes
    import uuid

    chemin = Path(chemin)
    if not chemin.exists():
        return None
    frontiere = "----kie" + uuid.uuid4().hex
    mime = mimetypes.guess_type(chemin.name)[0] or "application/octet-stream"

    def champ(nom, valeur):
        return (f"--{frontiere}\r\nContent-Disposition: form-data; name=\"{nom}\"\r\n\r\n"
                f"{valeur}\r\n").encode("utf-8")

    corps = (
        champ("uploadPath", "images/ferdinand")
        + champ("fileName", chemin.name)
        + (f"--{frontiere}\r\nContent-Disposition: form-data; name=\"file\"; "
           f"filename=\"{chemin.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8")
        + chemin.read_bytes()
        + f"\r\n--{frontiere}--\r\n".encode("utf-8")
    )
    # Domaine kieai.redpandaai.co et non api.kie.ai : l'endpoint documente sur
    # api.kie.ai renvoie 404, verifie sur un vrai appel.
    req = urllib.request.Request(
        "https://kieai.redpandaai.co/api/file-stream-upload", data=corps, method="POST")
    req.add_header("Authorization", f"Bearer {api_key()}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={frontiere}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("data") or {}).get("downloadUrl")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError,
            http.client.HTTPException, json.JSONDecodeError) as e:
        print(f"  Erreur reseau ({type(e).__name__}): {e}")
    return None


def generer_image(prompt, planche_url=None):
    """Image d'une scene, avec ou sans planche de style en reference.

    Avec planche, on passe par nano-banana-EDIT : la reference verrouille la
    palette, le traitement des decoupes et surtout l'apparence du personnage.
    Sans elle, le rendu derive d'une scene a l'autre - mesure sur des rendus
    reels, ou Ferdinand s'etait fait remplacer par un inconnu en photo
    decoupee.
    """
    if planche_url:
        data = create_and_wait(
            "google/nano-banana-edit",
            {"prompt": prompt, "image_urls": [planche_url],
             "image_size": "9:16", "output_format": "png"},
            max_wait=180,
        )
        if data:
            return data
        # Repli sans reference plutot que de perdre la scene. Une panne du
        # modele d'edition, ou une URL de planche expiree, faisait echouer
        # TOUTES les scenes et donc la video entiere - alors qu'un rendu au
        # style moins tenu reste exploitable. Signale comme incident.
        print("  ATTENTION : rendu avec planche indisponible, "
              "repli sur une generation sans reference.")
    return create_and_wait(
        "google/nano-banana",
        {"prompt": prompt, "image_size": "9:16", "output_format": "png"},
        max_wait=180,
    )


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
    if first_brace == -1:
        return text.strip()
    # raw_decode et non un decoupage jusqu'au DERNIER '}' : quand le modele
    # ajoute quoi que ce soit apres son JSON (un second objet, une phrase de
    # conclusion), le decoupage large ramenait les deux et json.loads echouait
    # sur "Extra data". Ici on lit le premier objet complet et on ignore la
    # suite. Constate sur un appel reel de decoupage en scenes.
    try:
        _, fin = json.JSONDecoder().raw_decode(text[first_brace:])
        return text[first_brace:first_brace + fin].strip()
    except ValueError:
        last_brace = text.rfind("}")
        if last_brace > first_brace:
            return text[first_brace:last_brace + 1].strip()
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
        # le trigger phrase (ex. "[curious] Pourquoi... ?") - on l'ignore
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


def generate_voice(text, out_path, lang="en", profil=None, timbre=None):
    """Voix d'une scene.

    `profil` remplace l'intention de jeu (dramatique, calme, proche du
    micro...) : sans lui, toutes les videos de la chaine sont lues exactement
    de la meme maniere. `timbre` choisit la voix elle-meme - sa valeur doit
    etre un nom accepte par le fournisseur, d'ou le repli sur celui qui a ete
    valide en production.
    """
    audio_profile = profil or lang_cfg(lang)["audio_profile"]
    task = create_task(
        "google/gemini-3-1-flash-tts",
        {
            "speakers": [
                {"speaker_id": "Speaker 1", "voice_name": timbre or "Zephyr",
                 "audio_profile": audio_profile,
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
    cas pour garder des parametres uniformes (h264/yuv420p/24fps, VIDEO_SCALE),
    necessaires pour le concat final en -c copy."""
    clip_path, out_path = Path(clip_path), Path(out_path)
    clip_dur = get_duration(clip_path)
    if clip_dur > target_duration + 0.1:
        # Rogne a la duree cible - reencode (un simple -c copy peut couper
        # sur un mauvais keyframe et donner un resultat imprecis/casse).
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(clip_path), "-t", f"{target_duration:.2f}",
             "-r", "24", "-vf", VIDEO_SCALE, "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-crf", CLIP_CRF, "-an", str(out_path)],
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
             "-t", f"{extra:.2f}", "-r", "24", "-vf", VIDEO_SCALE, "-pix_fmt", "yuv420p", str(freeze_tail)],
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
             "-r", "24", "-vf", VIDEO_SCALE, "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-crf", CLIP_CRF, "-an", str(out_path)],
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
             "-t", f"{extra:.2f}", "-r", "24", "-vf", VIDEO_SCALE, "-pix_fmt", "yuv420p", str(freeze_tail)],
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
    parser.add_argument("--lang", choices=sorted(LANGUAGES), default="en",
                         help="Langue du script et de la voix : en (defaut), fr, de.")
    parser.add_argument("--video-model", choices=["seedance", "runway"], default="runway",
                         help="runway = runway (defaut, le moins cher des deux, valide sur plusieurs runs) ; seedance = bytedance/seedance-1.5-pro (repli)")
    parser.add_argument("--quality", choices=sorted(RESOLUTIONS), default="720p",
                         help="Resolution demandee au modele video ET imposee au montage : "
                              "720p (defaut) ou 1080p, qui coute 2,5x plus cher chez "
                              "le fournisseur ($0.15 vs $0.06 par clip de 5s).")
    parser.add_argument("--out-dir", default=None,
                         help="Dossier de sortie (defaut: a cote du script). Utilise par le backend "
                              "pour isoler chaque job dans son propre dossier.")
    parser.add_argument("--no-subtitles", action="store_true",
                         help="Desactive les sous-titres animes incrustes (actifs par defaut).")
    parser.add_argument("--idea", default=None,
                         help="Titre impose, pioche par le backend dans la liste validee "
                              "(ideas_de.json). Sans lui, le script genere 10 idees et en "
                              "tire une au hasard.")
    parser.add_argument("--watermark", default=None,
                         help="Pseudo incruste en filigrane mobile. Par defaut, lit la "
                              "variable d'environnement WATERMARK ; vide = aucun filigrane.")
    parser.add_argument("--no-sfx", action="store_true",
                         help="Desactive les bruitages (actifs par defaut).")
    parser.add_argument("--style", choices=sorted(styles.TOUS), default=styles.DEFAUT,
                         help="Famille visuelle : vox (collage papier documentaire, defaut) ou "
                              "ferdinand (3D cinematique). Change le rendu des "
                              "images ET la direction d'animation - le collage demande "
                              "une camera mobile la ou le 3D la garde fixe.")
    parser.add_argument("--variation-index", type=int, default=None,
                         help="Rang du sujet dans sa liste validee. Sert a tirer la "
                              "charpente, l'ambiance et la voix dans un paquet battu, "
                              "pour que deux videos publiees a la suite ne se "
                              "ressemblent pas.")
    parser.add_argument("--cache-dir", default=None,
                         help="Dossier ou sont conservees les scenes deja produites, PARTAGE "
                              "entre toutes les tentatives d'un meme sujet. Sans lui, le cache "
                              "vit dans --out-dir, propre a chaque lancement, et une relance "
                              "repaie toutes les scenes.")
    # parse_known_args : le backend lance les deux scripts avec la meme base
    # d'arguments. Une option ajoutee a graphique.py seul ne doit pas faire
    # echouer celui-ci sur un "unrecognized arguments" invisible depuis
    # l'interface (c'est arrive trois fois dans l'autre sens).
    args, _ignores = parser.parse_known_args()

    # Sortie non bufferisee : le backend lit la progression ligne par ligne en
    # temps reel (sans ca, Python bufferise quand stdout n'est pas un terminal
    # et rien ne s'affiche avant la fin du process).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    global OUT_DIR, CACHE_DIR
    if args.out_dir:
        OUT_DIR = Path(args.out_dir)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR = Path(args.cache_dir) if args.cache_dir else OUT_DIR
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # La resolution doit etre posee AVANT la premiere scene : fit_clip_to_duration
    # lit VIDEO_SCALE a chaque clip, et le concat final refuserait des segments
    # de tailles differentes si elle changeait en cours de route.
    global VIDEO_QUALITY, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_SCALE
    VIDEO_QUALITY = args.quality
    VIDEO_WIDTH, VIDEO_HEIGHT = RESOLUTIONS[VIDEO_QUALITY]
    VIDEO_SCALE = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}"

    # Tout ce qui distingue cette video des autres, tire une fois ici. La
    # graine vient du titre impose : une relance du meme sujet redonne la meme
    # ambiance, sinon une reprise depuis le cache melangerait dans une seule
    # video des scenes de plein jour et des scenes de nuit.
    index = args.variation_index if args.variation_index is not None else 0
    var = variation.pour(args.idea or "sans-titre", index, args.lang)

    cfg_style = styles.get(args.style)
    # Le collage papier a ses propres variations de fond : les ambiances
    # lumineuses du 3D (« nuit aux lampadaires orange ») combattraient sa
    # palette archive. Chaque style pioche donc dans sa propre liste, avec le
    # meme paquet battu, pour que deux videos voisines different quand meme.
    ambiance = var.ambiance
    if cfg_style["ambiances"]:
        ambiance = variation._paquet(
            cfg_style["ambiances"], index, "ambiance-" + cfg_style["nom"])

    mode_cfg = MODES[args.mode]
    suffix = "" if args.mode == "short" else f"_{args.mode}"
    suffix += lang_cfg(args.lang)["suffix"]
    if args.video_model == "seedance":
        suffix += "_seedance"  # runway est desormais le defaut (pas de suffixe)
    # Sans ca, une video collage et une video 3D du MEME sujet ecriraient dans
    # les memes fichiers de cache et se reprendraient l'une l'autre.
    if cfg_style["nom"] != styles.DEFAUT:
        suffix += "_" + cfg_style["nom"]
    # Meme raison pour la resolution : relancer un sujet en 1080p apres un
    # essai en 720p doit regenerer les clips, pas reprendre les petits depuis
    # le cache - le concat final les refuserait de toute facon. Le 720p ne
    # prend pas de suffixe : c'est le defaut, et les caches deja sur le disque
    # sont du 720p sans suffixe.
    if VIDEO_QUALITY != "720p":
        suffix += "_" + VIDEO_QUALITY
    print(f"=== Mode : {args.mode} / Langue : {args.lang} / Video : {args.video_model} "
          f"/ Style : {cfg_style['nom']} / Resolution : {VIDEO_QUALITY} ===\n")
    print(f"  Variation : {var.resume(ambiance)}")
    print(f"  Style : {cfg_style['libelle']} | fond={ambiance.split(':')[-1].strip()[:44]}")

    # Planche de style : televersee une fois pour toute la video, puis jointe a
    # chaque prompt d'image. Les fichiers KIE expirent en 24h, donc on renvoie
    # a chaque generation plutot que de garder une URL. Absente ou upload en
    # echec, on continue sans - rendu moins tenu, mais pas de video perdue.
    planche_url = None
    if cfg_style["planche"]:
        planche = Path(__file__).parent / "planches" / cfg_style["planche"]
        planche_url = televerser(planche)
        if planche_url:
            print(f"  Planche de style : jointe ({planche.name})")
        else:
            # Prefixe ATTENTION : c'est ce que le backend reconnait comme
            # incident. Sans lui, la video sortait avec un style qui derive
            # d'une scene a l'autre et un personnage qui change, sans que rien
            # n'apparaisse a l'ecran pour l'expliquer.
            print(f"  ATTENTION : planche de style indisponible ({planche.name}), "
                  f"rendu sans reference visuelle - style et personnage moins tenus.")

    script_system = build_script_system(mode_cfg, lang=args.lang,
                                        charpente=var.charpente)
    trigger_phrase = lang_cfg(args.lang)["trigger"]

    idea_file = OUT_DIR / f"idea{suffix}.txt"
    script_file = OUT_DIR / f"script{suffix}.txt"
    scenes_file = OUT_DIR / f"scenes_raw{suffix}.json"
    audio_path = OUT_DIR / f"voice{suffix}.wav"  # assemble a l'etape 5 a partir des voix par scene

    if idea_file.exists() and script_file.exists() and scenes_file.exists():
        print(f"=== 1-3. Reprise depuis le cache ({idea_file.name}/{script_file.name}/{scenes_file.name}) ===")
        first_idea = idea_file.read_text(encoding="utf-8").strip()
        script = script_file.read_text(encoding="utf-8").strip()
        scenes = json.loads(scenes_file.read_text(encoding="utf-8"))["scenes"]
        reparer_personnage(scenes)
        print(f"Idee : {first_idea}")
        print(f"Script : {script}")
        print(f"{len(scenes)} scenes.")
    else:
        print("=== 1. Generation de l'idee ===")
        if args.idea:
            # Idee imposee par le backend, piochee dans la liste validee. Aucun
            # appel API ici : le titre a deja ete ecrit et relu a l'avance.
            first_idea = args.idea.strip()
            remember_idea(first_idea)
            print(f"-> Idee imposee : {first_idea}")
            idea_file.write_text(first_idea, encoding="utf-8")
            ideas_text = None
        else:
            ideas_text = claude(build_idea_system(args.lang), "Give me 10 ideas.", max_tokens=500)
        if not args.idea:
            if not ideas_text:
                print("ECHEC total sur la generation d'idees. Arret.")
                return
            print(ideas_text)
            # On prenait systematiquement la ligne 1, donc toujours la meme
            # idee d'une generation a l'autre : le modele proposait bien 10
            # titres varies, le code n'en regardait qu'un.
            candidates = [
                m.group(1).strip()
                for m in (re.match(r"^\s*\d+[\.\)]\s*(.+)", l) for l in ideas_text.splitlines())
                if m
            ]
            if not candidates:
                candidates = [ideas_text.splitlines()[0].strip()]

            used = load_used_ideas()
            fresh = [c for c in candidates if c.lower() not in used]
            if not fresh:
                print(f"  (les {len(candidates)} idees ont deja ete utilisees, on repioche)")
                fresh = candidates
            first_idea = random.choice(fresh)
            remember_idea(first_idea)
            print(f"\n-> Idee choisie : {first_idea}  ({len(fresh)}/{len(candidates)} inedites)")
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
            if not generate_voice(script, precheck_audio, lang=args.lang,
                              profil=var.profil_voix, timbre=var.timbre):
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
                    f"(step 4) with an extra step or two of genuine arithmetic. "
                    f"Do not pad with filler or repetition - add real additional substance."
                )
                candidate = generate_valid_script(script_system, longer_prompt, trigger_phrase)
                if not candidate:
                    print("  (echec de regeneration, on garde la version actuelle)")
                    break
                script = candidate
                print(script)
                script_file.write_text(script, encoding="utf-8")
                if not generate_voice(script, precheck_audio, lang=args.lang,
                              profil=var.profil_voix, timbre=var.timbre):
                    print("  (echec voix de controle sur la version etoffee, on garde la precedente)")
                    break
                audio_dur = get_duration(precheck_audio)
                print(f"  Nouvelle duree : {audio_dur:.1f}s")
            if audio_dur < 60:
                print(f"  ATTENTION : toujours sous 60s ({audio_dur:.1f}s) apres {min_duration_attempt} tentative(s) - on continue quand meme.")
            n_scenes_hint = max(8, min(20, round(audio_dur / SCENE_CLIP_SECONDS)))
        print(f"  -> ~{n_scenes_hint} scenes visees (indicatif ; la duree de chaque scene sera mesuree individuellement a l'etape 4)")

        print("\n=== 3. Decoupage en scenes (avec texte parle par scene) ===")
        scenes_system = build_scenes_system(n_scenes_hint, lang=args.lang,
                                            ambiance=ambiance, style=cfg_style)
        scenes_raw = claude(scenes_system, f"Script:\n{script}", max_tokens=6000)
        if not scenes_raw:
            print("ECHEC total sur le decoupage en scenes. Arret.")
            return
        scenes_raw = strip_json_fences(scenes_raw)
        scenes_file.write_text(scenes_raw, encoding="utf-8")
        scenes = json.loads(scenes_raw)["scenes"]
        reparer_personnage(scenes)
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
    # Dans le CACHE, pas dans le dossier du job : c'est ce qui permet a une
    # relance de reprendre les scenes deja payees au lieu de tout refaire.
    scenes_dir = CACHE_DIR / f"scenes{suffix}"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== 4. Generation scene par scene (voix individuelle + image + video calee sur sa duree) ===")
    for s in scenes:
        n = s["scene_no"]
        clip_path = scenes_dir / f"scene_{n:02d}.mp4"
        seg_audio_path = scenes_dir / f"scene_{n:02d}.wav"
        # Taille non nulle, pas seulement presence : un process tue en pleine
        # ecriture laisse un fichier de 0 octet qui passe .exists(). Mesure du
        # 03/10 : un clip vide a ete repris depuis le cache, ffmpeg l'a rejete
        # au concat ("moov atom not found") et la scene a disparu de la video
        # finale, sans que le bilan ne signale quoi que ce soit.
        if _utilisable(clip_path) and _utilisable(seg_audio_path):
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
        if not generate_voice(spoken_text, seg_audio_path, lang=args.lang,
                                 profil=var.profil_voix, timbre=var.timbre):
            print("  Echec voix de la scene.")
            continue
        seg_dur = get_duration(seg_audio_path)
        print(f"  Voix OK ({seg_dur:.2f}s) : {spoken_text[:60]!r}")

        print(f"=== Scene {n}/{n_scenes} : image ===")
        img_data = generer_image(s["image_prompt"], planche_url)
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
                    "quality": VIDEO_QUALITY,
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
                    "resolution": VIDEO_QUALITY,
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

    # Sous-titres et filigrane sont incrustes dans la MEME passe : chacun
    # dans la sienne doublerait le temps d'encodage, ce qui pese lourd sur les
    # 0,5 CPU de Render.
    overlays, described = [], []

    if not args.no_subtitles:
        ass_path = OUT_DIR / f"subs{suffix}.ass"
        n_lines = subtitles.build_ass(timeline_segments, ass_path,
                                      y=var.y_ferdinand,
                                      actif=var.couleur_active,
                                      inactif=var.couleur_inactive)
        if n_lines:
            overlays.append(subtitles.ass_filter(ass_path))
            described.append(f"sous-titres ({n_lines} mots)")
        else:
            print("  (aucun texte a sous-titrer)")

    wm_text = watermark.configured(args.watermark)
    if wm_text:
        wm_path = OUT_DIR / f"watermark{suffix}.ass"
        # La frise de la voix donne la duree exacte sans relire le fichier.
        total = sum(dur for _, dur in timeline_segments)
        if watermark.build_ass(total, wm_path, override=args.watermark,
                               waypoints=var.waypoints):
            overlays.append(subtitles.ass_filter(wm_path))
            described.append(f"filigrane {wm_text!r}")

    if overlays:
        print(f"  Incrustation : {', '.join(described)}...")
        burned = OUT_DIR / f"concat_subs{suffix}.mp4"
        result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(concat_video),
             "-vf", ",".join(overlays),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-an", str(burned)],
            check=False,
        )
        if result.returncode == 0 and burned.exists():
            concat_video = burned
            print(f"  Incrustation OK -> {burned}")
        else:
            # Non bloquant : une video sans sous-titres reste utilisable,
            # perdre 30 minutes de generation pour ca ne le serait pas.
            print("  ATTENTION : incrustation echouee, on continue sans.")

    # --- Bruitages -------------------------------------------------------
    # Melanges dans l'AUDIO, avant la fusion : la video n'est pas touchee,
    # donc sync_video_to_audio peut continuer a la copier sans reencoder.
    if not args.no_sfx and audio_path.exists():
        print("  Bruitages...")
        placed, warnings = sfx.plan(
            timeline_segments, [cue for _, _, _, cue in sub_segments],
            seed=var.graine_sfx,
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

    # --- Regeneration des pixels (optionnelle, desactivee par defaut) ----
    # Re-synthetise chaque image via un VAE sur un service GPU distant :
    # perturbation generique de tout signal invisible, efficacite
    # invérifiable (aucun fournisseur ne publie de detecteur). Degrade les
    # sous-titres, incrustes plus haut. Voir synthid_remove.py.
    if synthid_remove.is_enabled():
        print("  Regeneration des pixels (VAE distant) demandee...")
        synthid_out = OUT_DIR / f"final_synthid{suffix}.mp4"
        if synthid_remove.remove(final_video, synthid_out):
            final_video = synthid_out
            print(f"  Regeneration des pixels OK -> {final_video}")
        else:
            print("  ATTENTION : regeneration des pixels echouee, on continue avec la video d'origine.")

    # --- Nettoyage final du conteneur ------------------------------------
    # SYSTEMATIQUE, meme quand l'inspection ne trouve rien d'anormal - ce qui
    # est le cas usuel, les remux successifs du montage ayant deja fait
    # disparaitre ce que les modeles auraient pu poser. Deux raisons :
    #   - la passe est en copie de flux : pas de reencodage, pixels intacts,
    #     environ une seconde ;
    #   - elle applique +faststart, qui place l'index (moov) en tete de
    #     fichier. La lecture demarre alors sans attendre le telechargement
    #     complet, ce qui compte a l'upload et en streaming. Conditionner le
    #     nettoyage a la presence de marqueurs privait toutes les videos de
    #     ce gain, puisqu'on n'en trouve jamais.
    # Elle retire au passage les tags d'encodeur residuels (versions FFmpeg)
    # et tout marqueur de provenance IA qui serait present (C2PA...).
    try:
        avant = ai_metadata.inspect_video(final_video)
        if avant["has_ai_metadata"]:
            print(f"  Metadonnees IA detectees : {', '.join(avant['markers'])}")
        nettoyee = OUT_DIR / f"final_clean{suffix}.mp4"
        if ai_metadata.strip_metadata(final_video, nettoyee):
            final_video = nettoyee
            restants = ai_metadata.inspect_video(final_video)["markers"]
            if restants:
                print(f"  ATTENTION : marqueurs toujours presents apres nettoyage : "
                      f"{', '.join(restants)}")
            else:
                print(f"  Conteneur nettoye (+faststart) -> {final_video}")
        else:
            print("  ATTENTION : nettoyage du conteneur echoue, on continue avec la video d'origine.")
    except OSError as e:
        print(f"  ATTENTION : inspection du conteneur impossible ({e}), on continue.")

    # Bilan AVANT la ligne de fin : une scene ratee n'arrete pas le pipeline,
    # la video sort simplement plus courte. Sans ce compte, une video amputee
    # (credits epuises a la scene 12, le 27/09) est indiscernable d'une
    # reussite complete - ni dans le journal, ni a l'ecran.
    print(f"\n=== BILAN : {len(clip_paths)}/{n_scenes} scenes produites ===")
    if len(clip_paths) < n_scenes:
        print(f"ATTENTION : {n_scenes - len(clip_paths)} scene(s) manquante(s), "
              f"la video est plus courte que prevu.")

    print(f"\n=== TERMINE : {final_video} ===")


if __name__ == "__main__":
    main()
