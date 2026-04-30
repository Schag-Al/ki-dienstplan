# KI-Dienstplan MVP

Lokale und cloudfaehige Streamlit-Demo fuer ein KI-gestuetztes Dienstplanprogramm.

Die App nutzt keine echte KI-API. Die automatische Planung erfolgt lokal mit Google OR-Tools CP-SAT.

## Online-Test mit Streamlit Community Cloud

1. Projekt in ein GitHub-Repository hochladen.
2. Bei Streamlit Community Cloud anmelden.
3. Neues App-Projekt erstellen und das GitHub-Repository auswaehlen.
4. Als Hauptdatei `app.py` eintragen.
5. Deploy starten.

Streamlit installiert die Pakete automatisch aus `requirements.txt`.

## Lokaler Start

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Alternativ unter Windows:

```text
start_windows.bat
```

## Enthaltene Testdaten

Die App nutzt ausschliesslich Fantasienamen und Testdaten direkt in `app.py`.
Es werden keine echten Mitarbeiterdaten benoetigt.

## Funktionen

- Dienstplan fuer 1 bis 4 Wochen generieren
- Fruehdienst, Spaetdienst, Nachtdienst und Frei anzeigen
- Harte Regeln wie Sperrtage, Maximaldienste und Nachtgrenzen beachten
- Weiche Wuensche wie Nachtpraeferenz, Doppelnacht und Wochenende frei optimieren
- Auswertung pro Mitarbeiter anzeigen

## Hinweise

- Keine Datenbank
- Kein Login
- Keine Cloud-Abhaengigkeit ausser dem optionalen Hosting bei Streamlit Community Cloud
- Keine lokalen Dateien erforderlich
- CSV- und Excel-Dateien sind in `.gitignore` ausgeschlossen, damit keine echten Testdaten versehentlich hochgeladen werden
