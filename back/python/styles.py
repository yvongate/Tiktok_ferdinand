"""Familles de style visuel du format Ferdinand.

Le pipeline ne connaissait qu'un seul rendu : 3D semi-realiste facon cinematique.
Le style « vox » ajoute un second rendu complet - collage papier documentaire,
decoupes en couches dans la profondeur, camera qui traverse le diorama.

CE N'EST PAS UN SIMPLE CHANGEMENT DE STYLE_LOCK. La consigne de decoupage en
scenes est ecrite pour le 3D photorealiste et contredit le collage sur quatre
points :

  - elle interdit explicitement « infographic », « flat design », « 2D » - or
    le collage vit de ce vocabulaire-la ;
  - elle demande des « evidence boards » photorealistes pour les beats
    chiffres, la ou le collage veut de la typographie et des chiffres geants ;
  - elle peuple les plans de « OTHER PEOPLE » photorealistes, quand le collage
    veut des decoupes photo en noir et blanc tramees ;
  - surtout, elle impose une camera FIXE sur presque chaque plan (« real shots
    in this genre hold perfectly still »). Le collage documentaire fait
    exactement l'inverse : un mouvement de camera engage par plan, qui traverse
    les couches et revele la parallaxe. C'est ce mouvement qui fait le style.

D'ou deux jeux de consignes complets plutot qu'une variable.

Le piege a eviter, appris a mes depens : decrire le collage comme « plat » ou
« flat 2D » donne un plan quasi immobile et sans relief. Les decoupes sont des
couches PHYSIQUES separees dans l'espace, avec de la profondeur de champ et des
elements d'avant-plan qui fralent l'objectif. Papier en materiau, volume en
mise en scene.
"""

# --- Style historique : 3D semi-realiste ------------------------------
FERDINAND = {
    "nom": "ferdinand",
    "libelle": "Ferdinand 3D (rendu cinematique)",

    "role": "You are an AI visual director creating cinematic scenes in the exact visual style of viral 3D-animated YouTube Shorts, and an AI animation director writing motion prompts for an image-to-video model.",

    "style_lock": (
        "semi-realistic 3D CGI, GTA V / The Last of Us cutscene quality, realistic skin "
        "texture with visible pores, natural cinematic lighting, detailed real-world "
        "environment, photorealistic 3D render, no cartoon, no cel shading, no Pixar, "
        "no simple background, no studio backdrop"
    ),

    "note_personnage": "",

    "regle_mecanisme": "MECHANISM/REASON LITERALIZATION RULE: when a scene's beat reveals the hidden reason/mechanism behind the everyday feeling (a psychological trick, a pricing strategy, a banking mechanism, an economic principle), stage it as a literal, visual metaphor - photorealistic 3D-rendered - rather than just a character talking. Example patterns: a price tag physically changing from a round number to one ending in .99; a hand adjusting a store's shelf layout; a phone screen glowing with a notification designed to pull attention; a vault or ledger for a banking/interest mechanism; a puppet-string or magnet visual for a psychological pull. Pick whatever concrete visual best matches THIS specific mechanism - the reveal should coincide with the exact sentence that explains it in the script.",

    "regle_diagramme": "DIAGRAM / RUNNING-NUMBERS BEATS: when a beat is about numbers accumulating or a step-by-step breakdown (rather than a character action), do NOT describe a flat 2D infographic. Instead describe a photorealistic 3D \"evidence board\" or \"war room\" scene consistent with the style lock: a corkboard covered in printed documents, photos and string connections, or a glass wall/whiteboard covered in handwritten figures and taped receipts, or a holographic financial display in a dark room - something a thriller/heist movie would show a character analyzing. If a character is present in this kind of beat, keep them small in frame, in a observing/presenting stance, off to one side, so the numbers/documents stay the visual focus.",

    "regle_vivacite": """SCENE LIVELINESS RULE (critical - this is what stops scenes from feeling like "a character posed alone in an empty-feeling room"): every single scene must feel genuinely lived-in and populated, not just a nicely-detailed but static backdrop behind one posed character. For each scene, use at least one (mix and vary across scenes, don't repeat the same technique every time):
- A concrete prop/object directly tied to what that beat is saying (a phone showing a bank app, a receipt in hand, a laptop screen with a relevant page open, hands counting cash, a specific store shelf) - read the sentence and ask "what physical thing from this can I put in frame?"
- OTHER PEOPLE in the background or midground, doing something plausible for the location (other shoppers, coworkers at other desks, passersby on a street, other customers in line) - a real space has other people in it, not just the main character alone.
- Ambient activity/life in the environment (a TV or screen playing something in the background, steam from a coffee, traffic outside a window, someone walking past in the corridor).
Never leave a scene as just the character standing/posed in a pretty-but-static space with nothing else going on.""",

    "regle_animation": "Each animation_prompt (max 50 words): camera motion and subject motion described separately, ONE dominant motion, camera essentially STATIC/LOCKED for almost every scene - real shots in this genre hold perfectly still and let hard cuts carry the energy, not movement within the shot. Only allow subtle micro-motion (breathing, a slight blink, hair or paper stirring, a light flicker) unless the scene is the tense/reveal/final beat, where a slow push-in or slight handheld shake is allowed. Never describe camera movement as the default.",

    "interdits": 'Never use: "simple background", "clean background", "smooth skin", "vibrant colors", "cartoon", "Pixar", "octane render", "stylized", brand logos, "infographic", "flat design", "2D".',

    # None = utiliser les ambiances lumineuses de variation.py (comportement
    # historique : matin couvert, fin d'apres-midi, soir bleu...).
    "ambiances": None,

    # Le 3D n'a pas besoin de reference visuelle : le texte suffit a tenir
    # le rendu, prouve par des dizaines de videos.
    "planche": None,
}


# --- Style collage documentaire ---------------------------------------
# Architecture reprise d'une analyse de production : un bloc STYLE ecrit une
# fois et reutilise tel quel, un bloc ACTION qui seul change d'un plan a
# l'autre, et une liste d'interdits explicite. La liste d'interdits n'est pas
# cosmetique : c'est elle qui empeche le texte deforme et les logos inventes
# que le modele d'image ajoute spontanement (constate sur un essai reel).
VOX = {
    "nom": "vox",
    "libelle": "Collage documentaire (papier decoupe)",

    "role": "You are an AI visual director creating scenes for a hand-cut documentary paper-collage explainer, and an AI animation director writing motion prompts for an image-to-video model. Think archival newsprint cutouts staged as a physical diorama and filmed with a moving camera - not a flat infographic, and not glossy CG.",

    "style_lock": (
        "hand-cut documentary paper-collage, aged newsprint surface with visible print "
        "grain and torn paper edges, flat matte paper materials, desaturated archival "
        "palette of cream, oxidised grey and faded ink blue with exactly one hot signal "
        "red accent, black-and-white halftone photo cutouts with rough white keylines and "
        "offset red marker strokes; the cutouts are PHYSICAL LAYERS separated in real "
        "space at visibly different depths like a paper diorama, strong shallow depth of "
        "field, foreground paper elements crossing close to the lens, true parallax "
        "between layers; never glossy CG 3D, never a flat single-plane composition; "
        "the paper surfaces carry NO readable words - newsprint, labels and signage read "
        "as abstract grey type-texture only; digits may appear when the scene genuinely "
        "calls for a number, set large and alone, never invented headlines, never brand "
        "names, never sentences; "
        "THE WHOLE FRAME IS PRINTED MATTER - the setting itself is a cut-paper set or a "
        "printed black-and-white backdrop panel standing behind the figures, never a "
        "photographed real room; this is a composed editorial collage filling the frame "
        "edge to edge, never a photograph of a paper model sitting on a desk or table"
    ),

    # Planche de style jointe a chaque prompt d'image. Sans elle, deux
    # defauts mesures : le rendu derive vers la photo de bricolage en
    # papier, et Ferdinand se fait remplacer par un inconnu en photo
    # decoupee. La planche porte la palette, le traitement des decoupes et
    # surtout le personnage.
    "planche": "vox.png",

    # Ferdinand reste reconnaissable, mais en materiau papier. Son costume
    # rouge devient l'accent chaud unique de la palette : le style et la marque
    # se renforcent au lieu de se contredire.
    "note_personnage": "MASCOT IN THIS STYLE: render him as a hand-cut paper figure - a printed cutout with rough white keyline edges and slight drop shadow, standing as a physical layer inside the scene. Keep his design exactly as described (fox, deep-red three-piece suit, gold watch chain), but as printed matte paper, never as a 3D-rendered or photographic animal. CRITICAL: he is the ONLY figure in full colour - his orange fur and deep-red suit stay fully saturated while every other person in the frame is a colourless black-and-white halftone cutout. He is NEVER halftone, NEVER greyscale, never desaturated; that colour contrast is what makes him read as the host.",

    "regle_mecanisme": "MECHANISM/REASON LITERALIZATION RULE: when a scene's beat reveals the hidden reason/mechanism behind the everyday feeling, stage it as a physical paper-diorama metaphor rather than a character talking. Build it from cut paper: a price tag cutout flipping to reveal another number underneath, a paper hand sliding a shelf label, stacked paper coins sinking through a slot, a cut-paper magnet dragging halftone figures toward it, a folded arrow bending a queue of cutouts off its path. The mechanism must be readable as an object in space, with the reveal landing on the exact sentence that explains it.",

    "regle_diagramme": "DIAGRAM / RUNNING-NUMBERS BEATS: this style embraces editorial infographic language - but always built in DEPTH, never as a flat poster. Describe oversized condensed numerals cut from paper standing upright at different depths, arrows drawn card-to-card across the space, ticking counters on paper tabs, pinned receipts and clippings at varying distances from the lens, a route of paper coins crossing the frame. Keep one element crossing close to the lens and the background field softly out of focus, so the numbers read as physical objects in a diorama rather than a layout.\n\nTEXT RULE (critical - measured on real renders): image models draw DIGITS reliably and WORDS unreliably. Asked for headline type, they invent content: a German test render produced the meaningless words EUROWAVE, NUMER 1 and BOCL:A IDE, and a French one produced UNBETA SAVING. So never describe a headline, caption, sign, label or any readable word - describe printed surfaces as abstract grey type-texture instead. The ONLY lettering allowed is a number the script beat actually contains, set large and alone on a paper card or tag, digits only, with no word beside it.",

    "regle_vivacite": """SCENE LIVELINESS RULE: every scene must read as a populated, physically staged diorama, not one cutout alone on a background. For each scene, use at least one (vary across scenes):
- A cut-paper prop tied directly to what the beat says (a paper receipt, a halftone phone with a paper notification tab, a shelf of paper packets, a stack of paper notes).
- OTHER FIGURES as black-and-white halftone photo cutouts at different depths - shoppers, commuters, office workers - never rendered in full colour, always printed cutouts with white keylines.
- A background archival field within the palette: a faded map, a blueprint grid, a wall of newsprint read as grey type-texture, all softly out of focus behind the midground layers.
Never leave a scene as a single cutout on an empty paper field.""",

    # Le coeur du style. Une consigne de camera FIXE tuerait le rendu : c'est
    # le mouvement qui revele que les decoupes sont des couches separees.
    "regle_animation": """Each animation_prompt (50-70 words), written as three labelled parts on one line - ACTION:, AUDIO:, AVOID: - matching this pattern:
ACTION: ONE committed continuous camera move for the whole clip, and no cuts - pick one per scene and vary across scenes: orbit a quarter turn, fly between two layers, dive past a foreground element, slow push through the diorama, whip to a new layer, rack focus from one cutout to another. Layers must visibly parallax against each other on the move. Add element motion from this vocabulary: paper pieces springing in with overshoot, staggered entrances one after another, a counter ticking up, an underline swiping across, a tab flipping. End the move settled on the beat's key element.
AUDIO: sound design only, drawn from paper pops, thwips, stamps, ticks, whooshes, low newsroom hum - no music, no voice-over.
AVOID: no camera cuts within the clip, no new text appearing, no warped or gibberish letters, no glossy CG, no full-colour figures, no music, no narration.""",

    "interdits": 'Never use: "glossy", "CG render", "photorealistic", "3D render", "octane", "smooth skin", "vibrant colors", "Pixar", "cartoon", "cel shading", invented brand logos, real company logos, "clean background", "flat single plane", "static locked camera".',

    # Les ambiances lumineuses du style 3D (« nuit aux lampadaires orange »)
    # n'ont pas de sens sur du papier mat et combattraient la palette archive.
    # Ce qui varie ici d'une video a l'autre, c'est le FOND : le champ
    # documentaire sur lequel les couches sont posees.
    "ambiances": [
        "background field: a faded topographic map, heavily out of focus",
        "background field: a wall of narrow newsprint columns, softly blurred",
        "background field: a blueprint grid printed on blue paper, out of focus",
        "background field: an aged ledger page with faint ruled lines, blurred",
        "background field: weathered kraft paper with pinned scraps, out of focus",
    ],
}


TOUS = {s["nom"]: s for s in (FERDINAND, VOX)}
DEFAUT = "ferdinand"


def get(nom):
    """Style par son nom, avec repli sur l'historique.

    Le repli est volontaire : un nom inconnu ne doit pas faire echouer une
    generation deja payee en amont (idee, script), il doit produire la video
    habituelle.
    """
    return TOUS.get(nom or DEFAUT, FERDINAND)
