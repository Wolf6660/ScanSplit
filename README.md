# ScanSplit

<img src="web/assets/icon.png" alt="ScanSplit" width="110">

**Aus Doppelseiten werden einzelne A4-Seiten – im Browser, lokal auf deinem NAS oder Raspberry Pi.**

PDF hochladen, Seiten auswählen, Trennlinie verschieben und die fertige PDF herunterladen. ScanSplit kombiniert den Namen **ScanSplit** mit dem grünen Heft-Icon. Die Weboberfläche ist deutsch und benötigt keine externen Schriftarten, CDNs oder Cloud-Dienste zur Dokumentverarbeitung.

## Funktionen

- Vorschau mit Seitenminiaturen; gemischte Einzel- und Doppelseiten werden unterstützt.
- Pro Scan: ganze Seite, beide Hälften, nur links, nur rechts oder auslassen.
- Trennlinie direkt in der Vorschau ziehen oder per Regler/Tastatur einstellen.
- Seiten um 90° drehen und Einstellungen auf eine Mehrfachauswahl übertragen.
- Ausgabe als A4-PDF, proportional eingepasst. Links steht vor rechts.
- **Deutsche OCR ist standardmäßig aktiv und rot hinterlegt.** Der Schalter bleibt jederzeit vor einem Export abschaltbar. Ohne OCR wird nicht neu gerastert.
- OCR über Tesseract, seitenweise bei etwa 300 dpi. Ein Fehler führt zu einer verständlichen Fehlermeldung; OCR wird niemals stillschweigend abgeschaltet. Du kannst sie selbst ausschalten und erneut exportieren.
- Fortschritt, Warteschlange, Abbruch und PDF-Download. Ein Reload des Browser-Tabs stellt Dokument und letzten Auftrag wieder her.
- Original und fertige Ausgaben bleiben in einem Docker-Volume erhalten, bis du sie löschst oder die Aufbewahrungsfrist abläuft. Vorgabe: 24 Stunden; Bereinigung alle 30 Minuten und beim Dienststart.

## Schnellstart

Auf dem Docker-Host einen Projektordner anlegen und die [`compose.yml`](compose.yml) dorthin kopieren. Ein Git-Checkout auf dem Host ist nicht erforderlich: Das Basis-Image wird beim ersten Start direkt aus diesem GitHub-Repository gebaut.

```sh
docker compose up -d --build
```

Danach im Browser **`http://IP-DEINES-NAS:8080`** beziehungsweise **`http://IP-DEINES-PI:8080`** öffnen. Der erste Build und der erste Start benötigen Internetzugang und können einige Minuten dauern. Im Protokoll erscheinen Download, Versionsprüfung und anschließend der gestartete Webserver.

Die Python-Bibliothek wird inklusive Prüfsumme im Repository unter `vendor/` mitgeliefert. Die Installation beim Containerstart erfolgt ausschließlich aus diesen Dateien, **ohne Zugriff auf PyPI oder `files.pythonhosted.org`**. Für den Image-Build werden weiterhin Docker-/Debian-Paketserver benötigt; für Programmupdates GitHub.

Das Image verwendet `python:3.12-slim-bookworm` und ist für **Linux AMD64 und ARM64** ausgelegt. Für den Raspberry Pi ein 64-Bit-Betriebssystem verwenden. Auf Synology muss das konkrete Modell Container Manager/Docker unterstützen.

### Port in der YAML ändern

In `compose.yml`:

```yaml
ports:
  - "${SCANSPLIT_PORT:-8080}:8080"
```

Links steht der Port des NAS/Pi, rechts bleibt immer der interne Port `8080`. Für Port `8095` kannst du die Zeile direkt durch `"8095:8080"` ersetzen.

Alternativ `.env.example` nach `.env` kopieren und setzen:

```dotenv
SCANSPLIT_PORT=8095
```

Anschließend den Container neu erstellen. Die Oberfläche ist dann unter `http://IP-DEINES-NAS:8095` erreichbar. `environment.SCANSPLIT_PORT` in der YAML nicht ändern; dies ist der interne Port für Server und Healthcheck.

### Synology Container Manager

1. Einen Projektordner auf dem NAS anlegen und `compose.yml` darin speichern.
2. Im Container Manager unter **Projekt → Erstellen** den Ordner und die Compose-Datei auswählen.
3. Den gewünschten Host-Port in der YAML setzen und das Projekt bauen/starten.
4. Im Containerprotokoll auf die Meldung zum gestarteten Webserver warten, dann die NAS-IP mit dem eingestellten Port aufrufen.

Die beiden benannten Volumes werden automatisch angelegt. Ein manuelles Setzen von Dateirechten eines NAS-Bind-Mounts ist mit der Standardkonfiguration nicht nötig.

## Updates von GitHub

**Bei jedem Containerstart lädt der Einstiegspunkt die aktuelle Version von `main` von GitHub.** Neue Versionen bekommen eine eigene Python-Umgebung und werden vor der Aktivierung geprüft. Erst dann wird atomar auf diese Version umgeschaltet.

Für ein Anwendungsupdate reicht:

```sh
docker compose up -d --force-recreate
```

Auch ein normaler Container-Neustart führt die Aktualisierung aus. Bei unverändertem Git-Commit wird die bereits installierte Python-Umgebung wiederverwendet. Änderungen der Python-Anforderungen werden bei einem neuen Commit automatisch aus den mitgelieferten Wheels installiert. Paketdateien und SHA-256-Prüfsummen müssen im gleichen Commit enthalten sein.

Wenn GitHub vorübergehend nicht erreichbar ist oder die neue Version die Startprüfung nicht besteht, startet die letzte geprüfte Version aus dem persistenten Laufzeit-Cache. Ohne erste erfolgreiche Installation kann der Dienst nicht offline starten. Das Protokoll nennt diesen Rückfall ausdrücklich. `/api/health` zeigt die laufende Git-Revision an.

**Änderungen am Basis-Image** (Dockerfile, Systempakete, Einstiegspunkt) erfordern zusätzlich einen Image-Neubau:

```sh
docker compose build --pull --no-cache
docker compose up -d --force-recreate
```

Ein Container-Neuerstellen kann ein bereits gebautes Docker-Image nicht nachträglich verändern. Anwendungsdateien, Weboberfläche und Python-Abhängigkeiten werden dagegen ohne Neubau von GitHub aktualisiert.

Für einen festen Stand `SOURCE_REF` auf einen vorhandenen Tag setzen; mit `AUTO_UPDATE: "false"` wird nach der Erstinstallation die gecachte Version verwendet. Updates werden nur beim Start geladen, nicht während laufender PDF-Aufträge.

### Startfehler bei `files.pythonhosted.org`

Ältere Images haben Python-Pakete beim Start noch von PyPI heruntergeladen. Falls das Protokoll beim Laden von `pypdf` ein `Connection refused` meldet, einmal das Image mit dem neuen Einstiegspunkt neu bauen:

```sh
sudo docker compose build --pull --no-cache
sudo docker compose up -d --force-recreate
sudo docker compose logs --tail=100 scansplit
```

Dabei wird die neueste Version aus dem im Compose-Build-Kontext angegebenen GitHub-Branch verwendet. Die vorhandenen Volumes bleiben erhalten; sie müssen für diese Korrektur nicht gelöscht werden. Künftige Containerstarts installieren Python-Pakete aus dem GitHub-Checkout mit `--no-index` und Hashprüfung.

## Beispiel: Heft mit Cover auf einer A3-Fläche

Wenn beim Cover links eine leere Fläche und rechts das eigentliche Cover zu sehen ist, für diesen Scan **„Nur die rechte Hälfte“** wählen. Für die folgenden Doppelseiten **„Beide Hälften“** verwenden. Ein echter A4-Coverscan bleibt auf **„Ganze Seite“**.

## Betrieb und Einstellungen

| Einstellung | Vorgabe | Bedeutung |
|---|---|---|
| Host-Port | 8080 | Über `ports`/`.env` ändern |
| `SOURCE_REPO` | dieses Repository | Quelle für Updates; muss aus dem Container ohne interaktive Anmeldung lesbar sein |
| `SOURCE_REF` | main | Branch oder Tag |
| `AUTO_UPDATE` | true | Beim Start nach einer neuen Version suchen |
| `MAX_UPLOAD_MB` | 250 | Maximale PDF-Dateigröße |
| `MAX_PAGES` | 400 | Maximale Anzahl ursprünglicher Scans |
| `MAX_QUEUED_JOBS` | 4 | Höchstens vier laufende/wartende Aufträge insgesamt |
| `RETENTION_HOURS` | 24 | Aufbewahrungsfrist für hochgeladene Kopien und Ausgaben |
| `OMP_THREAD_LIMIT` | 1 | OCR-Parallelität begrenzen |

Es wird absichtlich **ein Export gleichzeitig** verarbeitet, um RAM und CPU kleiner Geräte zu schonen. Zwei begrenzte Vorschauplätze stehen separat bereit. `/tmp` ist auf 768 MB begrenzt und enthält nur temporäre Seitenbilder; vollständige Uploads und Ergebnisse liegen unter `/data`. Bei sehr großen oder komplexen Scans kann das Temp-Limit oder der Arbeitsspeicher erhöht werden müssen. Je Seite gilt ein Zeitlimit von fünf Minuten für externe Verarbeitungsschritte.

Die Oberfläche läuft ohne eingebaute Benutzeranmeldung und ist für das interne Netz vorgesehen. Für entfernten Zugriff eine bereits vorhandene VPN- oder authentifizierte Reverse-Proxy-Lösung verwenden. Proxy-Uploads müssen mindestens so groß wie `MAX_UPLOAD_MB` erlaubt sein; den ursprünglichen `Host`-Header weiterreichen.

Dokumentlinks enthalten zufällige Kennungen. ScanSplit führt keine öffentliche Dokumentliste und protokolliert keine Originaldateinamen oder vollständigen Dokument-URLs in HTTP-Zugriffslogs. Alle Browser-Ressourcen kommen vom eigenen Server. GitHub/PyPI werden für Programmupdates kontaktiert; PDF-Inhalte werden dorthin nicht übertragen.

Die Anwendung läuft als UID/GID `1000:1000`, ohne Root-Rechte, ohne Linux-Capabilities und mit schreibgeschütztem Root-Dateisystem. Die beiden Volumes und `/tmp` sind beschreibbar.

### Daten behalten oder löschen

- „Dateien löschen“ entfernt die hochgeladene Kopie und ihre Ergebnisse. Das Original auf deinem Gerät bleibt erhalten.
- Ein Container-Neuerstellen erhält beide benannten Volumes.
- **`docker compose down -v` entfernt die Volumes und damit gespeicherte PDFs sowie den Versions-Cache.**
- Bei einem Neustart unterbrochene Aufträge werden als fehlgeschlagen markiert und können erneut gestartet werden. Vollständig exportierte Ergebnisse bleiben bis zur Bereinigung erhalten.

## Entwicklung und Tests

Ohne Docker: Python 3.12, Poppler (`pdftoppm`) und optional Tesseract mit deutschen Sprachdaten installieren.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --no-index --find-links vendor --require-hashes -r requirements.txt
SCANSPLIT_DATA_DIR=./data python -m scansplit
python -m unittest discover -s tests -v
```

Für lokale Quellcodeänderungen im Container:

```sh
docker compose -f compose.yml -f compose.local.yml up --build
```

Die Tests prüfen PDF-Teilung, Scannerrotationen, A4-Maße, Originalschutz, Abbruch externer Prozesse, echte HTTP-Uploads/Vorschauen/Downloads und den Update-/Fallback-Mechanismus mit einem lokalen Git-Repository. Der OCR-Integrationstest verwendet echten Tesseract und wird nur ausgeführt, wenn Tesseract/Poppler installiert sind. GitHub Actions installiert diese Werkzeuge, führt die Tests aus und baut das Image für AMD64 und ARM64.

Der Bootstrap-Regressionstest installiert das echte mitgelieferte pypdf-Wheel in frische virtuelle Umgebungen bei abgeschaltetem Paketindex. Ein zusätzlicher Test manipuliert eine Paketdatei und prüft, dass die Installation wegen einer falschen Prüfsumme abgewiesen wird. Hinweise zum reproduzierbaren Neuverpacken der unveränderten Bibliothek stehen in `vendor/README.md`.

`tools/browser_check.cjs` ist ein optionaler Playwright-Test für die echte Oberfläche einschließlich rotem Standard-OCR-Schalter, Ziehen/Tastatursteuerung der Trennlinie, Mehrfachauswahl, Download, Reload und Mobilansicht. Seine Ergebnisse und alle Test-PDFs sind von Git ausgeschlossen.

## Technische Grenzen

Die automatische Vorschlagslogik erkennt Querformat, nicht den Inhalt einer Seite. Eine Heftfalz wird nicht automatisch erkannt. OCR ist nicht fehlerfrei; Spaltenreihenfolge, Tabellen und Sonderzeichen können abweichen. Mit OCR werden die fertigen Seiten neu gerastert; Dateigröße und Bilddarstellung können sich ändern. Ohne OCR bleiben PDF-Inhalte erhalten. Die visuelle Beschneidung ist **keine Schwärzungsfunktion** für vertrauliche Inhalte.

Das Icon basiert auf dem ausgewählten grünen Imagegen-Entwurf. Verwendete Komponenten: Python, pypdf (BSD-3-Clause), Poppler, Tesseract, Debian und deren jeweilige Lizenzen. ScanSplit enthält keine Kopien der privaten Beispielscans und keine Mac-App-Binärdateien.
