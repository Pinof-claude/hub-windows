# Hub

App Windows : consommation IA (Claude, ChatGPT), notes, transcription vocale. Données 100 % locales.

## Télécharger
GitHub > Actions > dernier run `build-windows` > artefact `Hub-windows` > dézipper > `Hub.exe`.

## Données
- `%APPDATA%\HubWindows\hub.db` : notes + transcriptions (SQLite).
- `%APPDATA%\HubWindows\audio\` : enregistrements WAV.
- `%APPDATA%\HubWindows\models\` : modèle Whisper `small` (téléchargé au 1er usage, ~460 Mo, connexion requise une fois).
- Clés API : Gestionnaire d'identification Windows.

## Consommation IA
- Claude Code : logs locaux `~/.claude/projects` (aucune clé).
- Claude API : clé admin Anthropic (`sk-ant-admin...`, console.anthropic.com > Settings > Admin keys).
- OpenAI API : clé admin OpenAI (platform.openai.com > Settings > Admin keys).
- Quotas abonnements Claude Pro/Max et ChatGPT Plus : non exposés par les éditeurs.

## Dev
```
pip install -r requirements.txt pytest
python main.py
python -m pytest -q
```
