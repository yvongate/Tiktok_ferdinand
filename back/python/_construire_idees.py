"""Construit la liste de sujets au format "Warum ... ?" (taupe).

Remplace le format precedent "Darum + sensation" : l'accroche devient une
QUESTION, et le sujet part d'une depense que le spectateur subit lui-meme.
Mesure sur 110 videos concurrentes : 97% de leurs accroches sont des
questions, et les sujets qui marchent touchent le portefeuille du
spectateur, pas l'actualite lointaine.

Usage : python _construire_idees.py  -> ecrit ideas_de_maulwurf.json
"""
import json
from pathlib import Path

# (allemand, francais) - le pipeline lit "de", le "fr" sert a la relecture.
CATEGORIES = {
    "kredit": [
        ("Warum ist der Zins bei kleinen Krediten am höchsten?", "Pourquoi le taux est-il le plus élevé sur les petits crédits ?"),
        ("Warum ist ein Handy auf Raten teurer als ein Autokredit?", "Pourquoi un téléphone à crédit coûte-t-il plus qu'un prêt auto ?"),
        ("Warum prüft dich der Anbieter, ohne dass du es merkst?", "Pourquoi es-tu évalué sans le savoir ?"),
        ("Warum ist die Ratenzahlung „zinsfrei\"?", "Pourquoi le paiement en plusieurs fois est-il « sans intérêts » ?"),
        ("Warum ist dein Dispo teurer als jeder Kredit?", "Pourquoi ton découvert coûte-t-il plus cher que n'importe quel crédit ?"),
        ("Warum ist die kleine Rate das teuerste Angebot?", "Pourquoi la petite mensualité est-elle l'offre la plus chère ?"),
        ("Warum steht die Rate groß und der Gesamtpreis klein?", "Pourquoi la mensualité est-elle écrite en grand et le prix total en petit ?"),
        ("Warum fragt dich der Händler nach deiner Rate statt nach deinem Budget?", "Pourquoi le vendeur demande-t-il ta mensualité plutôt que ton budget ?"),
        ("Warum kostet dich ein Kredit extra, wenn du ihn früher zurückzahlst?", "Pourquoi rembourser un crédit en avance coûte-t-il un supplément ?"),
        ("Warum verlängert dir die Bank so gern die Laufzeit?", "Pourquoi la banque propose-t-elle si volontiers d'allonger la durée ?"),
        ("Warum macht dich eine Umschuldung selten schuldenfrei?", "Pourquoi un rachat de crédit rend-il rarement libre de dettes ?"),
        ("Warum zahlst du bei „Jetzt kaufen, später zahlen\" am Ende mehr?", "Pourquoi « acheter maintenant, payer plus tard » coûte-t-il plus cher au final ?"),
        ("Warum will die Bank, dass du nur den Mindestbetrag zahlst?", "Pourquoi la banque veut-elle que tu ne payes que le minimum ?"),
        ("Warum ist deine Kreditkarte gratis, bis du sie wirklich brauchst?", "Pourquoi ta carte de crédit est-elle gratuite jusqu'à ce que tu en aies besoin ?"),
        ("Warum senkt eine Ratenpause deine Schulden nicht?", "Pourquoi une pause de mensualité ne réduit-elle pas ta dette ?"),
        ("Warum ist der beworbene Zinssatz fast nie deiner?", "Pourquoi le taux affiché n'est-il presque jamais le tien ?"),
        ("Warum kostet Geld leihen am wenigsten, wenn du es nicht brauchst?", "Pourquoi emprunter coûte-t-il le moins cher quand tu n'en as pas besoin ?"),
        ("Warum verkauft dir die Bank eine Versicherung zum Kredit?", "Pourquoi la banque vend-elle une assurance avec le crédit ?"),
        ("Warum ist die Finanzierung beim Händler die bequemste und teuerste?", "Pourquoi le financement chez le vendeur est-il le plus simple et le plus cher ?"),
        ("Warum ist der Nullzins ein Verkaufsinstrument?", "Pourquoi le taux zéro est-il un outil de vente ?"),
        ("Warum hilft dir ein Dispo nie aus dem Dispo?", "Pourquoi un découvert ne t'aide-t-il jamais à sortir du découvert ?"),
        ("Warum wird aus null Prozent am Ende doch ein Zins?", "Pourquoi zéro pour cent finit-il par devenir un taux ?"),
        ("Warum fragt dich beim Ratenkauf niemand, wofür du das Geld brauchst?", "Pourquoi personne ne demande-t-il à quoi sert l'argent ?"),
    ],
    "abo": [
        ("Warum ist der erste Monat gratis?", "Pourquoi le premier mois est-il gratuit ?"),
        ("Warum kündigst du das Abo nie, das du nicht nutzt?", "Pourquoi ne résilies-tu jamais l'abonnement que tu n'utilises pas ?"),
        ("Warum wird dein Vertrag teurer, wenn du nichts tust?", "Pourquoi ton contrat devient-il plus cher si tu ne fais rien ?"),
        ("Warum ist Kündigen schwerer als Abschließen?", "Pourquoi résilier est-il plus difficile que souscrire ?"),
        ("Warum bekommst du ein besseres Angebot, sobald du kündigst?", "Pourquoi obtiens-tu une meilleure offre dès que tu résilies ?"),
        ("Warum erinnert dich niemand an dein Probeabo?", "Pourquoi personne ne te rappelle-t-il ta période d'essai ?"),
        ("Warum gibt es für Neukunden immer den besseren Preis?", "Pourquoi les nouveaux clients ont-ils toujours le meilleur prix ?"),
        ("Warum rechnet sich dein Abo erst ab zehn Nutzungen im Monat?", "Pourquoi ton abonnement n'est-il rentable qu'à partir de dix utilisations ?"),
        ("Warum kostet dich Vergessen mehr als Entscheiden?", "Pourquoi oublier coûte-t-il plus cher que décider ?"),
        ("Warum wird die günstige Stufe immer unbequemer?", "Pourquoi la formule la moins chère devient-elle toujours plus pénible ?"),
        ("Warum zahlst du für Speicherplatz, den du nie gefüllt hast?", "Pourquoi payes-tu un espace de stockage jamais rempli ?"),
        ("Warum hast du Abos, von denen du nichts weißt?", "Pourquoi as-tu des abonnements dont tu ignores l'existence ?"),
        ("Warum ist ein Jahresabo eine Wette auf dich selbst?", "Pourquoi un abonnement annuel est-il un pari sur toi-même ?"),
        ("Warum läuft dein Vertrag automatisch weiter?", "Pourquoi ton contrat se reconduit-il tout seul ?"),
        ("Warum steigt der Preis immer erst nach einem Jahr?", "Pourquoi le prix n'augmente-t-il qu'après un an ?"),
    ],
    "bank": [
        ("Warum ist deine Hausbank meistens die teuerste Option?", "Pourquoi ta banque historique est-elle la plus chère ?"),
        ("Warum verlangt die Bank Gebühren für Papier?", "Pourquoi la banque facture-t-elle le papier ?"),
        ("Warum ist eine Überweisung am Freitagabend langsamer?", "Pourquoi un virement du vendredi soir met-il plus de temps ?"),
        ("Warum ist dein Konto „kostenlos\", aber du zahlst trotzdem?", "Pourquoi ton compte est-il « gratuit » alors que tu payes quand même ?"),
        ("Warum verdient die Bank an deinem Geld, das einfach daliegt?", "Pourquoi la banque gagne-t-elle sur ton argent qui dort ?"),
        ("Warum bekommst du auf dem Girokonto keine Zinsen?", "Pourquoi ton compte courant ne rapporte-t-il aucun intérêt ?"),
        ("Warum ist dein Jugendkonto plötzlich kostenpflichtig?", "Pourquoi ton compte jeune devient-il soudain payant ?"),
        ("Warum fragt dich der Automat im Ausland, ob du in Euro zahlen willst?", "Pourquoi le distributeur à l'étranger propose-t-il de payer en euros ?"),
        ("Warum ruft dich deine Bank an, wenn Geld eingeht?", "Pourquoi ta banque t'appelle-t-elle quand de l'argent arrive ?"),
        ("Warum empfiehlt dir deine Bank genau ihre eigenen Produkte?", "Pourquoi ta banque recommande-t-elle précisément ses propres produits ?"),
        ("Warum ist Tagesgeld nur für Neukunden gut verzinst?", "Pourquoi le livret n'est-il bien rémunéré que pour les nouveaux ?"),
        ("Warum wirbt die Bank mit einem Zins, den du nie bekommst?", "Pourquoi la banque affiche-t-elle un taux que tu n'auras jamais ?"),
        ("Warum kostet Kartenzahlung im Urlaub extra?", "Pourquoi payer par carte en vacances coûte-t-il un supplément ?"),
        ("Warum lohnt sich ein Bankwechsel fast immer und fast niemand macht ihn?", "Pourquoi changer de banque est-il presque toujours rentable et presque personne ne le fait ?"),
        ("Warum spürst du kontaktloses Bezahlen nicht?", "Pourquoi ne sens-tu rien en payant sans contact ?"),
        ("Warum rundet die App deine Käufe auf?", "Pourquoi l'appli arrondit-elle tes achats à l'euro supérieur ?"),
        ("Warum fragt die Kasse nach deiner Postleitzahl?", "Pourquoi la caisse demande-t-elle ton code postal ?"),
        ("Warum kostet Bargeld abheben manchmal Geld?", "Pourquoi retirer du liquide coûte-t-il parfois de l'argent ?"),
    ],
    "preis": [
        ("Warum machen dich Gratisproben zu Käufern?", "Pourquoi les échantillons gratuits te transforment-ils en acheteur ?"),
        ("Warum kostet dieselbe Fahrt je nach Uhrzeit mehr?", "Pourquoi le même trajet coûte-t-il plus selon l'heure ?"),
        ("Warum steigt der Preis, wenn du zögerst?", "Pourquoi le prix monte-t-il quand tu hésites ?"),
        ("Warum sind Bundles fast immer teurer?", "Pourquoi les lots sont-ils presque toujours plus chers ?"),
        ("Warum kaufst du die Verlängerung erst an der Kasse?", "Pourquoi achètes-tu l'extension seulement en caisse ?"),
        ("Warum kostet Personalisierung extra, obwohl sie nichts kostet?", "Pourquoi la personnalisation coûte-t-elle un supplément ?"),
        ("Warum ist der Lieferzeitpunkt plötzlich kostenpflichtig?", "Pourquoi choisir son créneau de livraison devient-il payant ?"),
        ("Warum gibst du mit Karte mehr aus als mit Bargeld?", "Pourquoi dépenses-tu plus en carte qu'en liquide ?"),
        ("Warum endet fast jeder Preis auf 9?", "Pourquoi presque tous les prix finissent-ils par 9 ?"),
        ("Warum steht neben dem teuren Angebot ein noch teureres?", "Pourquoi y a-t-il toujours une offre encore plus chère à côté ?"),
        ("Warum ist die mittlere Größe immer die „richtige\"?", "Pourquoi la taille moyenne est-elle toujours « la bonne » ?"),
        ("Warum wirkt ein durchgestrichener Preis günstig, auch wenn er nie galt?", "Pourquoi un prix barré paraît-il bon marché même s'il n'a jamais existé ?"),
        ("Warum kostet die kleine Packung mehr pro Gramm?", "Pourquoi le petit format coûte-t-il plus cher au gramme ?"),
        ("Warum bekommst du Rabatt, wenn du mehr kaufst, als du brauchst?", "Pourquoi une remise si tu achètes plus que nécessaire ?"),
        ("Warum macht dich Cashback ärmer?", "Pourquoi le cashback t'appauvrit-il ?"),
        ("Warum beginnt der Schlussverkauf, bevor die Saison endet?", "Pourquoi les soldes commencent-ils avant la fin de la saison ?"),
        ("Warum zeigt dir der Shop, wie viele andere gerade zuschauen?", "Pourquoi le site affiche-t-il combien de gens regardent ?"),
        ("Warum läuft der Countdown immer wieder von vorn?", "Pourquoi le compte à rebours recommence-t-il toujours ?"),
        ("Warum ist Versand erst ab einem bestimmten Betrag „kostenlos\"?", "Pourquoi la livraison n'est-elle « gratuite » qu'à partir d'un montant ?"),
        ("Warum legst du für 3 Euro Ersparnis 20 Euro mehr in den Korb?", "Pourquoi ajoutes-tu 20 € au panier pour en économiser 3 ?"),
        ("Warum ist das teuerste Produkt da, damit du es nicht kaufst?", "Pourquoi le produit le plus cher existe-t-il pour que tu ne l'achètes pas ?"),
        ("Warum ändert sich der Preis, je nachdem womit du suchst?", "Pourquoi le prix change-t-il selon l'appareil utilisé ?"),
        ("Warum zahlst du am Black Friday oft den Normalpreis?", "Pourquoi payes-tu souvent le prix normal le Black Friday ?"),
        ("Warum ist der erste Preis, den du siehst, dein Maßstab?", "Pourquoi le premier prix vu devient-il ta référence ?"),
        ("Warum kaufst du eher, wenn etwas „nur noch heute\" gilt?", "Pourquoi achètes-tu plus vite quand c'est « seulement aujourd'hui » ?"),
        ("Warum vergleichst du Prozente statt Euro?", "Pourquoi compares-tu des pourcentages plutôt que des euros ?"),
        ("Warum fühlt sich ein Gutschein wie ein Geschenk an?", "Pourquoi un bon d'achat ressemble-t-il à un cadeau ?"),
        ("Warum ist Rückgabe kostenlos und trotzdem teuer für dich?", "Pourquoi le retour gratuit te coûte-t-il quand même ?"),
        ("Warum kaufst du mehr, wenn du schon etwas gekauft hast?", "Pourquoi achètes-tu davantage après un premier achat ?"),
        ("Warum wirkt teuer manchmal einfach besser?", "Pourquoi « cher » semble-t-il parfois meilleur ?"),
        ("Warum kostet Bequemlichkeit immer am meisten?", "Pourquoi le confort coûte-t-il toujours le plus cher ?"),
        ("Warum ist die Großpackung manchmal teurer?", "Pourquoi le grand format est-il parfois plus cher ?"),
    ],
    "alltag": [
        ("Warum ist die Pfandflasche kein echtes Pfand?", "Pourquoi la consigne n'en est-elle pas vraiment une ?"),
        ("Warum werfen Supermärkte Essen weg, statt es zu verschenken?", "Pourquoi les supermarchés jettent-ils plutôt que de donner ?"),
        ("Warum ist das Mindesthaltbarkeitsdatum ein Verkaufsinstrument?", "Pourquoi la date limite est-elle un outil de vente ?"),
        ("Warum kostet dich ein vergessener Einkaufszettel zwanzig Euro?", "Pourquoi oublier sa liste coûte-t-il vingt euros ?"),
        ("Warum liegt die Milch ganz hinten im Laden?", "Pourquoi le lait est-il tout au fond du magasin ?"),
        ("Warum wird die Packung kleiner und der Preis bleibt?", "Pourquoi le paquet rétrécit-il à prix constant ?"),
        ("Warum steht das Teure auf Augenhöhe?", "Pourquoi le cher est-il à hauteur des yeux ?"),
        ("Warum riecht es am Eingang nach frischem Brot?", "Pourquoi ça sent le pain frais à l'entrée ?"),
        ("Warum gibt es im Supermarkt keine Fenster und keine Uhr?", "Pourquoi n'y a-t-il ni fenêtre ni horloge au supermarché ?"),
        ("Warum sind die Dinge, die du täglich brauchst, nie im Angebot?", "Pourquoi ce dont tu as besoin tous les jours n'est-il jamais en promo ?"),
        ("Warum liegen Süßigkeiten an der Kasse?", "Pourquoi les bonbons sont-ils en caisse ?"),
        ("Warum ist das Angebot nur mit App gültig?", "Pourquoi la promo n'est-elle valable qu'avec l'appli ?"),
        ("Warum sammelst du Punkte, die fast nichts wert sind?", "Pourquoi collectionnes-tu des points qui ne valent presque rien ?"),
        ("Warum kostet dich die Kundenkarte nichts?", "Pourquoi la carte de fidélité est-elle gratuite ?"),
        ("Warum wechselt der Laden ständig die Regale?", "Pourquoi le magasin réorganise-t-il sans cesse ses rayons ?"),
        ("Warum ist der Wocheneinkauf teurer, obwohl du eine Liste hattest?", "Pourquoi les courses dépassent-elles le budget malgré la liste ?"),
        ("Warum steht der Preis pro Kilo so klein?", "Pourquoi le prix au kilo est-il écrit si petit ?"),
        ("Warum ist Leitungswasser hundertmal günstiger als Flaschenwasser?", "Pourquoi l'eau du robinet est-elle cent fois moins chère ?"),
        ("Warum kostet Kaffee zu Hause ein Zehntel?", "Pourquoi le café à la maison coûte-t-il dix fois moins ?"),
        ("Warum ist Mittagessen holen teurer als ein Urlaub im Jahr?", "Pourquoi déjeuner dehors coûte-t-il plus qu'une semaine de vacances ?"),
        ("Warum sind kleine Ausgaben gefährlicher als große?", "Pourquoi les petites dépenses sont-elles plus dangereuses que les grandes ?"),
        ("Warum merkst du Abbuchungen nicht, aber Bargeld schon?", "Pourquoi ne remarques-tu pas les prélèvements, mais bien le liquide ?"),
        ("Warum ist Lieferung der teuerste Teil deines Essens?", "Pourquoi la livraison est-elle la part la plus chère de ton repas ?"),
        ("Warum kostet der Kaffee im Bahnhof das Doppelte?", "Pourquoi le café en gare coûte-t-il le double ?"),
    ],
    "versicherung": [
        ("Warum ist die Sterbegeldversicherung ein schlechtes Geschäft?", "Pourquoi l'assurance obsèques est-elle une mauvaise affaire ?"),
        ("Warum verkauft dir niemand die Versicherung, die du wirklich brauchst?", "Pourquoi personne ne te vend-il l'assurance vraiment utile ?"),
        ("Warum zahlst du für eine Garantie, die du schon hast?", "Pourquoi payer une garantie que tu as déjà ?"),
        ("Warum ist die Versicherung billig, bis du sie brauchst?", "Pourquoi l'assurance est-elle bon marché jusqu'au jour où tu en as besoin ?"),
        ("Warum versicherst du am liebsten das, was selten passiert?", "Pourquoi assures-tu surtout ce qui arrive rarement ?"),
        ("Warum lohnt sich eine Selbstbeteiligung fast immer?", "Pourquoi une franchise est-elle presque toujours rentable ?"),
        ("Warum steigt dein Beitrag, obwohl du nie einen Schaden hattest?", "Pourquoi ta cotisation augmente-t-elle sans aucun sinistre ?"),
        ("Warum brauchst du die Handyversicherung nicht?", "Pourquoi l'assurance téléphone est-elle inutile ?"),
        ("Warum ist die wichtigste Versicherung die langweiligste?", "Pourquoi l'assurance la plus importante est-elle la plus ennuyeuse ?"),
        ("Warum verkauft dir jeder eine Versicherung und niemand eine Kündigung?", "Pourquoi tout le monde te vend une assurance et personne une résiliation ?"),
        ("Warum zahlt die Reiseversicherung oft nicht?", "Pourquoi l'assurance voyage ne paye-t-elle souvent pas ?"),
        ("Warum kostet Monatszahlung mehr als Jahreszahlung?", "Pourquoi payer au mois coûte-t-il plus cher qu'à l'année ?"),
        ("Warum bekommt der Berater Geld, wenn du unterschreibst?", "Pourquoi le conseiller est-il payé quand tu signes ?"),
        ("Warum hast du zu viele Versicherungen und trotzdem die falschen?", "Pourquoi as-tu trop d'assurances et pourtant les mauvaises ?"),
        ("Warum endet der Schutz genau dann, wenn du ihn brauchst?", "Pourquoi la couverture s'arrête-t-elle quand tu en as besoin ?"),
        ("Warum ist deine Hausratversicherung zu hoch oder zu niedrig?", "Pourquoi ton assurance habitation est-elle mal calibrée ?"),
    ],
    "vertrag": [
        ("Warum kostet dich Treue beim Anbieter Geld?", "Pourquoi la fidélité te coûte-t-elle de l'argent ?"),
        ("Warum ist der Wechselbonus höher als deine Ersparnis?", "Pourquoi la prime de bienvenue dépasse-t-elle ton économie ?"),
        ("Warum ist das Handy „geschenkt\", wenn du den Vertrag nimmst?", "Pourquoi le téléphone est-il « offert » avec le forfait ?"),
        ("Warum kostet dein Strom mehr, obwohl du weniger verbrauchst?", "Pourquoi ton électricité coûte-t-elle plus cher alors que tu consommes moins ?"),
        ("Warum wird dein Tarif nach zwei Jahren teurer?", "Pourquoi ton forfait augmente-t-il après deux ans ?"),
        ("Warum zahlst du für Datenvolumen, das du nie nutzt?", "Pourquoi payes-tu des gigas que tu n'utilises jamais ?"),
        ("Warum bekommst du eine Prämie fürs Wechseln, aber nicht fürs Bleiben?", "Pourquoi une prime pour partir, aucune pour rester ?"),
        ("Warum ist die Grundgebühr der eigentliche Preis?", "Pourquoi l'abonnement fixe est-il le vrai prix ?"),
        ("Warum steht die Vertragslaufzeit im Kleingedruckten?", "Pourquoi la durée d'engagement est-elle en petits caractères ?"),
        ("Warum zahlst du Miete für den Router?", "Pourquoi loues-tu ta box ?"),
        ("Warum bekommst du nie die beworbene Internetgeschwindigkeit?", "Pourquoi n'as-tu jamais le débit annoncé ?"),
        ("Warum lohnt sich der Tarifwechsel beim selben Anbieter?", "Pourquoi changer d'offre chez le même opérateur est-il rentable ?"),
        ("Warum ist dein Abschlag höher als dein Verbrauch?", "Pourquoi ta mensualité dépasse-t-elle ta consommation ?"),
        ("Warum schickt dir dein Anbieter die Preiserhöhung per Post?", "Pourquoi la hausse de prix arrive-t-elle par courrier ?"),
    ],
    "sparen": [
        ("Warum ist „sicher\" das teuerste Wort in der Geldanlage?", "Pourquoi « sûr » est-il le mot le plus cher en placement ?"),
        ("Warum kostet dich jedes Umschichten Steuern?", "Pourquoi chaque arbitrage te coûte-t-il des impôts ?"),
        ("Warum ist der Bausparvertrag deiner Eltern heute wertlos?", "Pourquoi le plan épargne-logement de tes parents ne vaut-il plus rien ?"),
        ("Warum frisst die Inflation dein Sparbuch?", "Pourquoi l'inflation dévore-t-elle ton livret ?"),
        ("Warum kostet dich Warten mehr als Investieren?", "Pourquoi attendre coûte-t-il plus cher qu'investir ?"),
        ("Warum sind ein Prozent Gebühren nach dreißig Jahren ein Drittel deines Geldes?", "Pourquoi 1 % de frais équivaut-il à un tiers de ton argent en 30 ans ?"),
        ("Warum ist die Rendite auf dem Papier nicht deine Rendite?", "Pourquoi le rendement affiché n'est-il pas le tien ?"),
        ("Warum lohnt sich Sparen erst, wenn es automatisch passiert?", "Pourquoi épargner ne marche-t-il que si c'est automatique ?"),
        ("Warum ist dein Sparplan besser als dein Timing?", "Pourquoi un versement régulier bat-il le bon moment ?"),
        ("Warum verlierst du Geld, wenn du es sicher parkst?", "Pourquoi perds-tu de l'argent en le mettant à l'abri ?"),
        ("Warum ist Gold kein Einkommen?", "Pourquoi l'or ne produit-il aucun revenu ?"),
        ("Warum ist deine Lebensversicherung keine Geldanlage?", "Pourquoi ton assurance-vie n'est-elle pas un placement ?"),
        ("Warum wirbt niemand für das günstigste Produkt?", "Pourquoi personne ne fait-il la publicité du produit le moins cher ?"),
        ("Warum macht dich der Zinseszins erst spät reich?", "Pourquoi les intérêts composés n'agissent-ils que tard ?"),
        ("Warum ist dein größter Kostenfaktor unsichtbar?", "Pourquoi ton plus gros poste de frais est-il invisible ?"),
        ("Warum ist dein Notgroschen wichtiger als deine Rendite?", "Pourquoi ton épargne de précaution compte-t-elle plus que ton rendement ?"),
        ("Warum solltest du Schulden tilgen, bevor du investierst?", "Pourquoi rembourser avant d'investir ?"),
        ("Warum ist der durchschnittliche Anleger schlechter als der Durchschnitt?", "Pourquoi l'épargnant moyen fait-il moins bien que la moyenne ?"),
    ],
    "steuer": [
        ("Warum zahlst du eine Steuer auf eine Steuer?", "Pourquoi payes-tu une taxe sur une taxe ?"),
        ("Warum ist die kalte Progression eine unsichtbare Steuererhöhung?", "Pourquoi la progressivité froide est-elle une hausse d'impôt invisible ?"),
        ("Warum kostet dich ein Nebenjob mehr Steuern als erwartet?", "Pourquoi un second emploi est-il plus taxé que prévu ?"),
        ("Warum bleibt von deiner Gehaltserhöhung so wenig übrig?", "Pourquoi reste-t-il si peu de ton augmentation ?"),
        ("Warum zahlt dein Vermieter weniger Steuern als du?", "Pourquoi ton propriétaire paye-t-il moins d'impôts que toi ?"),
        ("Warum lohnt sich eine Steuererklärung fast immer?", "Pourquoi une déclaration est-elle presque toujours rentable ?"),
        ("Warum ist dein Netto nicht dein Geld?", "Pourquoi ton net n'est-il pas ton argent ?"),
        ("Warum kostet dich dein Job mehr, als auf dem Zettel steht?", "Pourquoi ton travail coûte-t-il plus que ce qui est écrit ?"),
        ("Warum ist die Steuerklasse keine Steuerersparnis?", "Pourquoi la classe d'imposition n'est-elle pas une économie ?"),
        ("Warum bekommst du Geld zurück, das dir immer gehörte?", "Pourquoi te rembourse-t-on de l'argent qui t'appartenait déjà ?"),
        ("Warum sind Werbungskosten der einfachste Gewinn?", "Pourquoi les frais professionnels sont-ils le gain le plus facile ?"),
        ("Warum zahlst du Steuern auf Zinsen, die die Inflation aufgefressen hat?", "Pourquoi payer l'impôt sur des intérêts mangés par l'inflation ?"),
        ("Warum lohnt sich der Freistellungsauftrag und fast niemand stellt ihn?", "Pourquoi l'exonération est-elle rentable et presque jamais demandée ?"),
        ("Warum ist Weihnachtsgeld besonders hoch besteuert?", "Pourquoi la prime de fin d'année est-elle si taxée ?"),
        ("Warum ist Schenken zu Lebzeiten günstiger als Vererben?", "Pourquoi donner de son vivant coûte-t-il moins que léguer ?"),
        ("Warum kostet Erben Geld?", "Pourquoi hériter coûte-t-il de l'argent ?"),
        ("Warum ist das Dienstrad günstiger als dieselbe Summe bar?", "Pourquoi le vélo de fonction coûte-t-il moins que la même somme en liquide ?"),
    ],
    "wohnen": [
        ("Warum ist die Maklerprovision beim Kauf so hoch?", "Pourquoi la commission d'agence est-elle si élevée à l'achat ?"),
        ("Warum zahlst du Grunderwerbsteuer auf etwas, das dir noch nicht gehört?", "Pourquoi payer des droits sur un bien pas encore à toi ?"),
        ("Warum ist eine Altbauwohnung im Unterhalt teurer?", "Pourquoi l'ancien coûte-t-il plus cher à entretenir ?"),
        ("Warum zahlst du Miete und baust nichts auf?", "Pourquoi payer un loyer sans rien construire ?"),
        ("Warum ist Kaufen nicht automatisch besser als Mieten?", "Pourquoi acheter n'est-il pas forcément mieux que louer ?"),
        ("Warum sind Nebenkosten die zweite Miete?", "Pourquoi les charges sont-elles un second loyer ?"),
        ("Warum bekommst du deine Kaution so schwer zurück?", "Pourquoi récupérer sa caution est-il si difficile ?"),
        ("Warum steigt deine Miete, obwohl sich nichts ändert?", "Pourquoi ton loyer augmente-t-il sans que rien ne change ?"),
        ("Warum kostet Umziehen mehr als bleiben, selbst bei höherer Miete?", "Pourquoi déménager coûte-t-il plus que rester, même plus cher ?"),
        ("Warum ist die möblierte Wohnung teurer als die leere?", "Pourquoi le meublé coûte-t-il plus cher que le vide ?"),
        ("Warum ist deine Heizkostenabrechnung immer zu hoch?", "Pourquoi ta régularisation de chauffage est-elle toujours trop élevée ?"),
        ("Warum ist der Kaufpreis nur der Anfang?", "Pourquoi le prix d'achat n'est-il que le début ?"),
        ("Warum zahlst du für Quadratmeter, die du nie betrittst?", "Pourquoi payes-tu des mètres carrés où tu ne vas jamais ?"),
        ("Warum ist ein WG-Zimmer teurer pro Quadratmeter als eine Wohnung?", "Pourquoi une colocation coûte-t-elle plus cher au m² ?"),
        ("Warum zahlst du Strom für den Hausflur?", "Pourquoi payes-tu l'électricité des parties communes ?"),
        ("Warum lohnt sich Renovieren vor allem für den Vermieter?", "Pourquoi rénover profite-t-il surtout au propriétaire ?"),
        ("Warum war das Eigenheim deiner Eltern kein Vermögen?", "Pourquoi la maison de tes parents n'était-elle pas un patrimoine ?"),
    ],
    "auto": [
        ("Warum ist die Anschlussgarantie beim Auto so teuer?", "Pourquoi l'extension de garantie auto est-elle si chère ?"),
        ("Warum verliert dein Auto in der ersten Minute Geld?", "Pourquoi ta voiture perd-elle de l'argent dès la première minute ?"),
        ("Warum ist Leasing bequem und teuer?", "Pourquoi le leasing est-il pratique et cher ?"),
        ("Warum kostet dich das günstige Auto am meisten?", "Pourquoi la voiture pas chère coûte-t-elle le plus ?"),
        ("Warum ist dein Auto zu fünfundneunzig Prozent der Zeit nutzlos?", "Pourquoi ta voiture est-elle inutile 95 % du temps ?"),
        ("Warum ist die Vollkasko nach fünf Jahren Verschwendung?", "Pourquoi l'assurance tous risques devient-elle inutile après cinq ans ?"),
        ("Warum kostet ein Jahreswagen fast wie ein Neuwagen?", "Pourquoi une voiture d'un an coûte-t-elle presque le prix du neuf ?"),
        ("Warum zahlst du für Winterreifen zweimal?", "Pourquoi payes-tu deux fois pour tes pneus hiver ?"),
        ("Warum ist der Spritpreis morgens anders als abends?", "Pourquoi le carburant change-t-il de prix dans la journée ?"),
        ("Warum ist die Inspektion teurer als nötig?", "Pourquoi la révision coûte-t-elle plus que nécessaire ?"),
        ("Warum ist Carsharing günstiger, als du denkst?", "Pourquoi l'autopartage coûte-t-il moins que tu ne crois ?"),
    ],
    "digital": [
        ("Warum verschwinden gekaufte Filme aus deiner Bibliothek?", "Pourquoi des films achetés disparaissent-ils de ta bibliothèque ?"),
        ("Warum gehört dir dein E-Book nicht?", "Pourquoi ton livre numérique ne t'appartient-il pas ?"),
        ("Warum kostet dich ein alter Akku ein neues Handy?", "Pourquoi une batterie usée coûte-t-elle un téléphone neuf ?"),
        ("Warum ist die App gratis, wenn du das Produkt bist?", "Pourquoi l'appli est-elle gratuite si tu es le produit ?"),
        ("Warum kostet das Spiel nichts und trotzdem viel?", "Pourquoi le jeu gratuit coûte-t-il si cher ?"),
        ("Warum schenkt dir die App Geld für einen Freund?", "Pourquoi l'appli te donne-t-elle de l'argent pour un ami ?"),
        ("Warum endet das Gratis-Guthaben im spannendsten Moment?", "Pourquoi le crédit gratuit s'arrête-t-il au meilleur moment ?"),
        ("Warum kaufst du Spielwährung statt Geld auszugeben?", "Pourquoi achètes-tu une monnaie virtuelle plutôt que dépenser ?"),
        ("Warum ist dein Cloudspeicher immer fast voll?", "Pourquoi ton stockage est-il toujours presque plein ?"),
        ("Warum ist der Preis in der App höher als im Browser?", "Pourquoi le prix dans l'appli dépasse-t-il celui du navigateur ?"),
        ("Warum zeigt dir die Plattform genau das, was du gerade angeschaut hast?", "Pourquoi la plateforme te montre-t-elle ce que tu viens de regarder ?"),
        ("Warum kostet Lieferung per App mehr als im Restaurant?", "Pourquoi commander via l'appli coûte-t-il plus cher qu'au restaurant ?"),
        ("Warum ist die kostenlose Variante absichtlich unbequem?", "Pourquoi la version gratuite est-elle volontairement pénible ?"),
    ],
    "arbeit": [
        ("Warum ist Homeoffice für deinen Arbeitgeber billiger?", "Pourquoi le télétravail coûte-t-il moins cher à l'employeur ?"),
        ("Warum bekommst du einen Titel statt einer Gehaltserhöhung?", "Pourquoi reçois-tu un titre plutôt qu'une augmentation ?"),
        ("Warum bekommst du mehr Gehalt beim Wechseln als beim Bleiben?", "Pourquoi gagne-t-on plus en changeant d'emploi qu'en restant ?"),
        ("Warum sind Überstunden oft unbezahlt?", "Pourquoi les heures supplémentaires sont-elles souvent non payées ?"),
        ("Warum nennt dir niemand im Betrieb das Gehalt der anderen?", "Pourquoi personne ne te dit-il le salaire des autres ?"),
        ("Warum kostet dich ein unbezahltes Praktikum doppelt?", "Pourquoi un stage non payé coûte-t-il double ?"),
        ("Warum ist eine Gehaltserhöhung unter der Inflation eine Kürzung?", "Pourquoi une augmentation sous l'inflation est-elle une baisse ?"),
        ("Warum zahlt dein Chef lieber Boni als Gehalt?", "Pourquoi ton patron préfère-t-il les primes au salaire ?"),
        ("Warum lohnt sich Teilzeit später weniger als gedacht?", "Pourquoi le temps partiel coûte-t-il cher plus tard ?"),
        ("Warum ist der Firmenwagen kein Geschenk?", "Pourquoi la voiture de fonction n'est-elle pas un cadeau ?"),
        ("Warum bringt dir eine Beförderung manchmal weniger Geld?", "Pourquoi une promotion rapporte-t-elle parfois moins ?"),
        ("Warum verhandelt niemand das Einstiegsgehalt und alle bereuen es?", "Pourquoi personne ne négocie-t-il son premier salaire ?"),
    ],
    "gesundheit": [
        ("Warum ist dasselbe Medikament im Ausland billiger?", "Pourquoi le même médicament est-il moins cher à l'étranger ?"),
        ("Warum zahlst du beim Arzt für ein Blatt Papier?", "Pourquoi payer un simple certificat chez le médecin ?"),
        ("Warum bietet dir der Arzt eine Leistung an, die die Kasse nicht zahlt?", "Pourquoi le médecin propose-t-il un acte non remboursé ?"),
        ("Warum kostet dieselbe Brille beim Optiker das Dreifache?", "Pourquoi les mêmes lunettes coûtent-elles trois fois plus ?"),
        ("Warum sind Zahnersatz und Zuzahlung so teuer?", "Pourquoi les prothèses dentaires coûtent-elles si cher ?"),
        ("Warum lohnt sich die private Krankenversicherung später nicht mehr?", "Pourquoi l'assurance santé privée se retourne-t-elle contre toi ?"),
        ("Warum zahlt die Kasse die günstigere Variante nicht?", "Pourquoi la caisse ne rembourse-t-elle pas l'option la moins chère ?"),
        ("Warum sind Nahrungsergänzungsmittel so profitabel?", "Pourquoi les compléments alimentaires sont-ils si rentables ?"),
    ],
    "rente": [
        ("Warum ist Riester für viele ein Verlustgeschäft?", "Pourquoi le plan Riester fait-il perdre de l'argent à beaucoup ?"),
        ("Warum reicht deine Rente nicht, obwohl du immer gezahlt hast?", "Pourquoi ta retraite ne suffit-elle pas malgré une vie de cotisations ?"),
        ("Warum ist die Rentenlücke größer, als die Post dir schreibt?", "Pourquoi l'écart de retraite est-il plus grand qu'annoncé ?"),
        ("Warum zahlst du Steuern auf deine Rente?", "Pourquoi payes-tu des impôts sur ta retraite ?"),
        ("Warum lohnt sich früh anfangen mehr als viel einzahlen?", "Pourquoi commencer tôt bat-il verser beaucoup ?"),
        ("Warum kostet dich jedes Jahr Warten spürbar Rente?", "Pourquoi chaque année d'attente coûte-t-elle cher ?"),
        ("Warum ist die betriebliche Altersvorsorge nicht immer gut?", "Pourquoi la retraite d'entreprise n'est-elle pas toujours avantageuse ?"),
        ("Warum sind Rentenpunkte kein Geld?", "Pourquoi les points retraite ne sont-ils pas de l'argent ?"),
    ],
    "freizeit": [
        ("Warum kostet das Ticket mehr als das Ticket?", "Pourquoi le billet coûte-t-il plus cher que le billet ?"),
        ("Warum sind Konzertpreise plötzlich dynamisch?", "Pourquoi les prix de concert deviennent-ils dynamiques ?"),
        ("Warum will das Fitnessstudio nicht, dass du kommst?", "Pourquoi la salle de sport ne veut-elle pas que tu viennes ?"),
        ("Warum kostet derselbe Flug morgen mehr?", "Pourquoi le même vol coûte-t-il plus cher demain ?"),
        ("Warum zahlst du für Sitzplatz, Gepäck und Einchecken extra?", "Pourquoi payer en plus le siège, le bagage et l'enregistrement ?"),
        ("Warum kostet Geldwechseln am Flughafen am meisten?", "Pourquoi changer de l'argent à l'aéroport coûte-t-il le plus cher ?"),
        ("Warum ist das Hotel im Paket günstiger und schlechter?", "Pourquoi l'hôtel en formule est-il moins cher et moins bon ?"),
        ("Warum ist die Jahreskarte erst ab zwölf Besuchen günstig?", "Pourquoi l'abonnement annuel n'est-il rentable qu'à douze visites ?"),
        ("Warum ist die Reiserücktrittsversicherung an der Kasse am teuersten?", "Pourquoi l'assurance annulation coûte-t-elle le plus cher à la caisse ?"),
    ],
}


def main():
    entrees, vus = [], set()
    n = 0
    for cat, paires in CATEGORIES.items():
        for de, fr in paires:
            cle = de.lower().strip()
            if cle in vus:
                print(f"DOUBLON ignore : {de}")
                continue
            vus.add(cle)
            n += 1
            entrees.append({"cat": cat, "fr": fr, "de": de, "n": n})

    cible = Path(__file__).parent / "ideas_de.json"
    cible.write_text(json.dumps(entrees, ensure_ascii=False, indent=1), encoding="utf-8")

    # Version lisible pour la relecture humaine. Le francais n'est la que
    # pour relire : c'est la colonne allemande qui part en production.
    lignes = [
        f"# {len(entrees)} sujets a valider",
        "",
        "Format : une QUESTION par video, le mecanisme se revele en chiffres.",
        "Le francais sert a la relecture. **C'est la colonne allemande qui",
        "part reellement en production.**",
        "",
    ]
    for cat, paires in CATEGORIES.items():
        lignes += ["", f"## {cat}  ({len(paires)})", ""]
        for e in (x for x in entrees if x["cat"] == cat):
            lignes.append(f"  {e['n']}. {e['fr']}")
            lignes.append(f"     `{e['de']}`")
    (Path(__file__).parent / "ideas_de.md").write_text(
        "\n".join(lignes) + "\n", encoding="utf-8"
    )

    print(f"{len(entrees)} sujets ecrits -> {cible.name} + ideas_de.md")
    for cat, paires in CATEGORIES.items():
        print(f"  {cat:<14} {len(paires):>3}")
    trop_long = [e for e in entrees if len(e["de"]) > 85]
    if trop_long:
        print(f"\n{len(trop_long)} titre(s) > 85 caracteres :")
        for e in trop_long:
            print(f"  [{len(e['de'])}] {e['de']}")


if __name__ == "__main__":
    main()
