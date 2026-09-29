# zing — vérification de la réalité des relais LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · **🇫🇷 Français** · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** est un outil en ligne de commande local-first qui vérifie si un relais d'API
(revendeur / proxy) sert réellement le modèle qu'il annonce — ou s'il le remplace
discrètement par un modèle moins cher, tronque votre fenêtre de contexte, simule le
streaming ou gonfle la facturation des tokens. Bref : en avez-vous pour votre argent ?
Il parle **OpenAI Chat Completions**, l'**API Anthropic Messages** et l'**API OpenAI
Responses** (`/v1/responses`) — détection automatique, ou forcée avec
`--api openai|anthropic|responses`.

Vous lui indiquez l'endpoint d'un relais et le modèle qu'il annonce ; zing exécute une
batterie de sondes en boîte noire, compare le comportement observé à une base de
connaissances intégrée de **85 profils de modèles natifs répartis sur 7 plateformes**,
et produit un verdict clair, étayé par des preuves — pour un humain, ou en JSON pour
qu'un autre outil / LLM le lise.

> zing fournit des **preuves en boîte noire de divergences et de risques, pas une
> preuve cryptographique de fraude.** Voir [Utilisation responsable](#utilisation-responsable).

---

## Pourquoi

Le marché des clés de relais regorge d'offres « GPT-4o pour un dixième du prix ».
Beaucoup sont honnêtes. Certaines ne le sont pas — et les malhonnêtes sont difficiles à
repérer à l'œil nu :

- Vous demandez `gpt-4o` ; on vous sert discrètement `gpt-4o-mini` ou un modèle ouvert.
- Le relais annonce un contexte de 1M de tokens mais tronque silencieusement à 32K.
- Le « streaming » est la réponse complète mise en tampon puis redécoupée, sans aucun gain de latence.
- Les tokens `usage` déclarés sont gonflés, et votre solde fond plus vite qu'il ne le devrait.
- Un modèle censé prendre en charge l'appel d'outils / le mode JSON ne le fait discrètement pas.

zing transforme « quelque chose cloche » en un rapport reproductible.

## Installation

Nécessite Python 3.10+. Chacune des options ci-dessous fournit la commande `zing`.

### Avec pip

```bash
# depuis PyPI
pip install zing-audit

# ou depuis les sources
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Avec [uv](https://docs.astral.sh/uv/)

```bash
# depuis PyPI, comme outil autonome dans votre PATH
uv tool install zing-audit

# ou l'exécuter une fois sans l'installer
uvx --from zing-audit zing --help

# ou depuis les sources, dans un environnement virtuel local au projet
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows : .venv\Scripts\activate
```

Vous pouvez aussi installer directement depuis le dépôt Git sans le cloner :
`uv tool install git+https://github.com/cenbonew/zing`.

(Mainteneurs : voir [docs/PUBLISHING.md](docs/PUBLISHING.md) pour le processus de publication.)

### Extras optionnels

- `tokenizers` — comptage précis des tokens pour la famille OpenAI dans l'audit de facturation.
- `web` — l'interface web locale (`zing serve`).

```bash
pip install 'zing-audit[tokenizers,web]'          # pip, depuis PyPI
pip install -e '.[tokenizers,web]'                # pip, depuis les sources
uv tool install 'zing-audit[tokenizers,web]'      # uv, depuis PyPI
uv pip install -e '.[tokenizers,web]'             # uv, depuis les sources
```

## Démarrage rapide

```bash
# 1) auditer un relais par rapport à ce qu'il annonce (id du modèle + indice de fournisseur)
export ZING_API_KEY=sk-votre-cle-relais
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) le contrôle le plus fort : comparer à une référence de confiance du même modèle
export OPENAI_API_KEY=sk-votre-cle-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditer un relais natif Anthropic (API Messages) — le protocole est détecté
#    automatiquement à partir de base_url/model, ou forcé avec --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confirmer une substitution suspectée : auditer l'id RÉEL du modèle du relais par
#    rapport au profil sous lequel il est vendu (ici : un modèle Doubao vendu comme deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) consulter la base de connaissances intégrée
zing kb            # les 85 modèles
zing kb deepseek   # un fournisseur

# 6) générer une configuration que vous pouvez versionner
zing init          # écrit zing.yaml
zing check -c zing.yaml
```

### Comme outil pour un LLM / agent

zing est conçu pour être piloté par un autre programme ou modèle. Tout est envoyé sur
stdout en JSON, erreurs comprises, et le code de sortie sert de verrou.

```bash
# verdict léger, adapté aux agents (~5x plus petit que --json : sans les preuves volumineuses)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# rapport structuré complet lorsque vous avez besoin des preuves de chaque constat
zing check --base-url ... --model gpt-4o --json

# budget d'abord : quels détecteurs s'exécutent + appels d'API estimés, SANS en faire aucun
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# verrou sur le code de sortie (1 si risque >= medium) ; les erreurs de config/usage sortent en 2, en JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# découverte lisible par machine
zing kb --json                 # toute la base de connaissances
zing models --base-url ... --json   # ce qu'un endpoint annonce
```

En mode `--json`/`--compact`, une configuration invalide affiche `{"error": {...}}`
(code 2) au lieu d'un message pour humain, afin qu'un pipeline puisse analyser les
échecs de manière uniforme.

## Interface web (`zing serve`)

Vous préférez cliquer ? Une interface web locale enveloppe le même moteur — pas besoin
de la ligne de commande.

```bash
pip install 'zing-audit[web]'     # ou : uv tool install 'zing-audit[web]'
zing serve            # ouvre http://localhost:8000
```

Saisissez un relais et le modèle qu'il annonce ; suivez l'audit **en direct**
(progression par détecteur via SSE), puis lisez un rapport de verdict partageable (note,
détail par dimension, constats en langage clair, JSON téléchargeable). Tout s'exécute
sur votre machine — une clé saisie dans le navigateur n'atteint que votre serveur local
et le relais cible, jamais un tiers. L'écoute reste sur `127.0.0.1` par défaut.

Un menu déroulant de langue dans l'en-tête de chaque page bascule l'interface entre
**🇬🇧 anglais** (par défaut), **🇨🇳 chinois** (l'interface d'origine), **🇫🇷 français**,
**🇪🇸 espagnol**, **🇵🇹 portugais**, **🇮🇹 italien** et **🇩🇪 allemand** ; le choix est
mémorisé par navigateur. Les rapports téléchargés depuis l'interface (**Télécharger le
rapport (JSON)**) suivent aussi la langue choisie : les clés JSON, les valeurs
d'énumération (`risk_level`, `status`, `severity`, …), les identifiants et les preuves
restent exactement comme dans le rapport de la CLI (c'est toujours un rapport zing
valide), tandis que les valeurs lisibles par un humain (titre/résumé du verdict,
titres/résumés des constats, recommandations, noms des détecteurs, notes) sont
traduites, et le nom du fichier porte la langue (`zing-report.fr.json`). Les rapports
`--format json|md|html` de la CLI restent en anglais.

**Les prompts envoyés à l'endpoint audité ne suivent pas la langue de l'interface.**
Chaque texte que zing envoie à une API de LLM — sondes de chat, prompt du juge LLM,
schémas d'outils, entrées d'embedding / rerank / image / audio — se trouve dans une
seule bibliothèque de prompts, `zing/prompts/en.json`, et est en anglais : le même
relais obtient ainsi le même verdict quel que soit le lecteur du rapport (les
vérifications de réponses et les estimations de tokens sont calibrées sur ces textes
exacts). Les seules exceptions sont les empreintes de la base de connaissances dont la
langue *est* la mesure — par ex. les sondes de fluidité en chinois, de tokenizer et
d'auto-identification des modèles natifs chinois — qui déclarent `prompt_lang` et une
raison `language_bound` dans `zing/knowledge/data/*.yaml`. Chaque rapport enregistre
les langues de sonde réellement utilisées (`prompt_languages`, par ex. `["en", "zh"]`).

Les traductions sont des données, partagées par l'interface web et les alertes webhook :
`zing/i18n/locales/<code>.json`, un fichier par langue. Pour ajouter une langue,
ajoutez un fichier (copiez `de.json`) ; le menu déroulant, les pages et les alertes le
prennent en compte. `tests/test_web_locales.py` échoue tant que chaque chaîne de
l'interface et chaque constat ne sont pas traduits avec leurs espaces réservés et leur
balisage intacts.

## Ce qui est vérifié

zing note dix dimensions. Les trois qui révèlent le plus directement une tromperie sur
la marchandise (identité du modèle, fenêtre de contexte réelle, capacités annoncées)
pèsent le plus.

| Dimension | Ce qu'elle détecte |
|---|---|
| **model_identity** | Rétrogradation/substitution silencieuse du modèle — auto-identification, date limite des connaissances, empreintes de tokenizer, champ `model` renvoyé |
| **context_window** | Troncature silencieuse du contexte (1M annoncé, le rappel échoue à 32K) et « perte au milieu » due à des couches RAG/résumé bon marché, via aiguille dans une botte de foin + recherche dichotomique |
| **capability** | Capacités annoncées d'appel d'outils / mode JSON / json-schema / sortie maximale non réellement fournies (ou *sur*-fournies, signe d'un substitut) ; et **vision** — un modèle annonçant l'entrée d'images reçoit une image générée à réponse connue pour confirmer qu'il « voit » vraiment |
| **billing** | Gonflement des tokens/de l'usage et comptabilité d'usage manquante/invérifiable, via une estimation indépendante par tokenizer |
| **streaming** | Faux streaming (tampon puis découpage) détecté à partir du nombre de fragments et de leur espacement temporel |
| **protocol** | Conformité à la compatibilité OpenAI : multi-tours, séquences d'arrêt, forme des réponses, schéma d'erreur — et une sous-vérification de déterminisme pour la mise en cache de réponses qui ignore temperature/seed |
| **reliability** | Taux de succès en concurrence et latence (la limitation HTTP 429 est comptée à part) |
| **performance** | La *régularité* de la latence, du délai du premier token et du débit, le taux d'échec de la sonde et le ralentissement sous charge ; la vitesse seulement face à une référence |
| **connectivity** | Accessibilité de l'endpoint et liste `/v1/models` annoncée |
| **security** | Transport (HTTPS), hygiène des en-têtes, écho de secrets ; prompt système injecté caché (surcoût fixe de tokens d'entrée + fuite), altération en transit des réponses/appels d'outils via des canaris à réponse connue (substitution d'URL/de paquet), et mise en cache de préfixe de prompt (temporisation) |

Voir [docs/METHODOLOGY.md](docs/METHODOLOGY.md) pour la technique derrière chaque
vérification, l'astuce de relais à laquelle elle correspond et ses mises en garde sur
les faux positifs.

### Performance

Chaque rapport comporte aussi une section **performance** : latence, temps jusqu'au
premier token (TTFT), tokens/s en décodage et de bout en bout, latence et gigue entre
fragments, taux d'erreurs/timeouts/429, une décomposition réseau (connexion TCP, TLS,
aller-retour `GET /models`, temps serveur) et démarrage à froid, chacun en
count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev. Quand la sonde dédiée s'exécute, elle note la dimension **performance** (poids 6) selon la *régularité* de la latence, du TTFT et du débit, le taux d'échec et le comportement sous charge, et non selon la vitesse brute : un modèle lent mais régulier (p. ex. local) n'est pas pénalisé. La vitesse ne compte que face à une référence (la référence de confiance ou la plage publiée dans la base de connaissances). Les constats sont au plus de sévérité faible et ne changent jamais le verdict de risque.

- **standard** la collecte à partir des propres requêtes de l'audit.
- **deep / full** ajoutent une sonde dédiée : 100 requêtes non cachables de 128 tokens
  de sortie (un identifiant de requête aléatoire ouvre chaque prompt, aucun paramètre de
  cache ou de raisonnement n'est envoyé) plus une rafale à `--concurrency`. Réglable avec
  `--performance-requests` (0 la désactive) et `--performance-max-tokens`.
- La sonde utilise le streaming par défaut ; `--performance-non-streaming` (ou
  l'interrupteur de l'interface web) mesure les relais qui ne savent pas streamer.
  **full** mesure les deux modes, entrelacés, et les présente côte à côte.
- **compare** exécute la sonde sur les deux endpoints, en alternant les requêtes, et
  ajoute un tableau cible-vs-référence (5 requêtes par côté en `standard`) dont les
  écarts sont marqués en vert ✓ lorsque la cible est meilleure et en rouge ✗ lorsqu'elle
  est moins bonne. Une cible qui génère plus de 2x plus vite que la référence est
  signalée comme un indice de faible gravité.

Les tokens sont comptés deux fois : à partir du `usage` du relais et localement, de
sorte que le débit reste mesurable même quand `usage` est absent. Un percentile n'est
affiché qu'avec assez d'échantillons (p90 à partir de 10, p95 à partir de 20, p99 à
partir de 100). Le rapport JSON conserve les temps de chaque requête (uniquement des
nombres, aucun texte) ; le rapport HTML et l'interface web les représentent sur la
chronologie de l'audit.

## Deux modes de détection

- **Code pur (par défaut) :** toutes les sondes déterministes — empreintes, balayage du
  contexte, calculs de facturation, temporisation du streaming. Aucun second modèle
  requis ; entièrement reproductible.
- **Hybride code + LLM (`--judge`) :** consulte en plus un modèle juge *de confiance*
  (configuré séparément, jamais la cible) pour évaluer des signaux flous comme la
  qualité et la profondeur de raisonnement que le code seul ne peut trancher. Alimente
  le détecteur `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

## Surveillance (`zing watch`)

Un relais peut servir le vrai modèle aujourd'hui et le remplacer discrètement la
semaine prochaine. `zing watch` relance l'audit selon un planning, enregistre chaque
exécution dans l'historique et alerte un webhook lorsque le risque franchit un seuil ou
**régresse** par rapport à l'exécution précédente.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang fr                                     # ou --once pour cron
```

Les alertes sont formatées pour **Slack / Feishu / DingTalk / JSON générique**,
détectées automatiquement à partir de l'URL du webhook, et rédigées dans la langue
d'alerte — l'anglais par défaut ; `--alert-lang en|zh|fr|es|pt|it|de`. La charge utile
JSON générique conserve ses clés et ses valeurs machine (`risk_level`, `score`, …)
indépendantes de la langue, traduit celles lisibles par un humain (`text`, `headline`,
`key_findings`) et indique la `language`.

Vous préférez une interface ? `zing serve` intègre un moniteur sur **`/watches`**
(🔔 Surveillances) : ajoutez une surveillance dans le navigateur et un planificateur en
arrière-plan, dans le même processus, la relance à son intervalle, enregistre chaque
exécution dans l'historique et déclenche les mêmes alertes webhook en cas de
franchissement de seuil ou de régression. Chaque surveillance a sa propre langue
d'alerte (choisie dans le formulaire, par défaut celle de l'interface, et modifiable
sur sa carte). Exécution immédiate / pause / suppression depuis la page. Les clés sont
stockées uniquement dans `~/.zing` et ne sont jamais renvoyées au navigateur.

## Audits d'embedding et de rerank

Les embeddings et le rerank sont une surface hors chat : zing les audite donc avec un
auditeur autonome dédié plutôt qu'avec le pipeline de chat à 9 dimensions.

```bash
# La dimension de vecteur attendue est résolue depuis la base intégrée pour le modèle annoncé.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou forcer directement la dimension attendue :
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank : une sonde intégrée à réponse connue — un vrai reranker doit classer
# en premier le document manifestement pertinent.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` vérifie la connectivité, la **correspondance de dimension** (longueur du vecteur
renvoyé vs dimension native du modèle annoncé — le signal phare de tromperie sur la
marchandise ; un relais annonçant `text-embedding-3-large` en 3072-d mais renvoyant du
1024-d sert un modèle substitué), le déterminisme (même entrée → cosinus ≈ 1), la
distinction (entrées sans rapport → cosinus bien inférieur à 1) et le champ `model`
renvoyé. Profils intégrés : OpenAI `text-embedding-3-small` (1536),
`text-embedding-3-large` (3072), `text-embedding-ada-002` (1536), Qwen
`text-embedding-v3`/`-v4` (1024).

Les deux sont aussi disponibles dans l'interface web — `zing serve` propose une page
**Outils** sur `/tools` (accessible depuis la navigation) avec des formulaires
embed/rerank qui affichent le même verdict localisé.

## Audits de génération d'images et d'audio (TTS)

Deux autres surfaces hors chat : la génération d'images (`POST /v1/images/generations`)
et la synthèse vocale (`POST /v1/audio/speech`). Tout le décodage se fait en stdlib pure
— dimensions d'image à partir des octets d'en-tête (PNG/JPEG/GIF/WebP), durée WAV via le
module `wave`.

```bash
# Un relais annonçant DALL·E 3 renvoie-t-il vraiment le 1792x1024 demandé ? Une image
# réduite / de mauvaise taille (ou une taille hors des tailles natives du modèle annoncé,
# résolues depuis la base) est le signal phare de tromperie sur la marchandise.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relais annonçant tts-1-hd renvoie-t-il un vrai audio dont la durée suit l'entrée
# (pas un substitut fixe, pas du HTML/JSON déguisé en audio) ?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` vérifie : connectivité, format valide/décodable, **correspondance de taille**
(LxH décodé vs la requête et les tailles natives du modèle annoncé — FAIL/HIGH en cas
d'écart), distinction (deux prompts → images différentes, pour repérer un substitut
fixe), nombre, champ model. `audio` vérifie : connectivité, validité du conteneur/format,
respect du format, durée non triviale (proportionnelle à la longueur de l'entrée),
distinction, champ model. La base inclut OpenAI DALL·E 2/3, gpt-image-1,
tts-1/tts-1-hd/gpt-4o-mini-tts et des profils image/TTS Qwen.

## Utilisation en CI (GitHub Action)

Conditionnez n'importe quel workflow à un audit de relais avec l'action composite
fournie. Elle exécute `zing check --compact --fail-on-risk`, expose `risk` / `score` /
`rating` comme sorties, écrit un résumé dans l'exécution et fait échouer le job lorsque
le seuil de risque est atteint.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.9.0          # épingler sur un tag de release
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # secret de l'appelant ; jamais affiché
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

La clé du relais est transmise via une variable d'environnement (`--api-key env:…`) et
n'apparaît donc jamais sur une ligne de commande. Voir [docs/CI.md](docs/CI.md) pour le
tableau complet des entrées/sorties et un exemple de conditionnement de déploiement.

## Suites

| Suite | Détecteurs | Coût |
|---|---|---|
| `smoke` | connectivity, security | très faible |
| `standard` | + protocol, model_identity, capability, streaming, billing, reliability | faible à moyen |
| `deep` | + context_window, determinism, injected_prompt, integrity, performance, prompt_cache, quality_judge (avec `--judge`) | plus élevé (les sondes de contexte long et de temporisation coûtent des tokens) |
| `full` | tout | le plus élevé |
| `custom` | seulement les dimensions choisies, en profondeur `deep` | selon la sélection |

**Suite personnalisée :** `zing check ... -D protocol -D performance` (ou `--suite custom --dimension billing,streaming` ; dans le fichier de configuration `run.dimensions`) n'exécute que les dimensions choisies. Le score global est la moyenne pondérée de ces seules dimensions ; sans dimension centrale (identité du modèle, fenêtre de contexte, capacités), le verdict de risque est *non concluant*. L'interface web propose le même choix.

La sonde de fenêtre de contexte est bornée par `--max-context-tokens` (200K par défaut),
de sorte qu'auditer un modèle à 1M de tokens reste abordable.

## Exemple de verdict

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • S'identifie comme une marque concurrente (anthropic) sous l'id de modèle annoncé gpt-4o
  • Fenêtre de contexte réelle ~8000 << 128000 déclarés (troncature silencieuse suspectée)
  • Les tokens de prompt déclarés dépassent largement l'estimation indépendante
```

Les rapports sont écrits dans `reports/` en JSON, Markdown et HTML.

## Base de connaissances

Les profils se trouvent dans [`zing/knowledge/data/`](zing/knowledge/data) sous forme de
YAML modifiable — un fichier par fournisseur (OpenAI, Anthropic, Google Gemini,
DeepSeek, Qwen, GLM, Moonshot). Chaque modèle porte sa fenêtre de contexte native, sa
sortie maximale, son tokenizer, ses indicateurs de capacités, ses mots-clés d'identité
et ses empreintes comportementales. Ajoutez ou remplacez des profils sans forker :

```bash
zing check --kb-dir ./my-profiles ...     # ou définir ZING_KB_DIR
```

## Utilisation responsable

zing est une aide à l'audit en boîte noire. Il **ne peut pas prouver** :

- qu'un fournisseur stocke vos prompts ou s'en sert pour l'entraînement,
- qu'il route toujours vers un seul modèle précis (un relais peut router de façon probabiliste),
- une fraude à la facturation au-delà de ce que l'estimation indépendante des tokens peut suggérer.

Utilisez les rapports pour votre propre vérification préalable. **N'accusez pas
publiquement un fournisseur** sur la base d'une seule exécution sans examiner la taille
de l'échantillon, les paramètres de coût et le droit local. Lancez `zing compare`
contre une référence de confiance avant de tirer des conclusions fortes.

## Licence

[Apache-2.0](LICENSE)
