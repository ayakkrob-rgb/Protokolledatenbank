# Protokolldatenbank der Fachschaft Medizin

Webseite, auf der Studierende Gedächtnisprotokolle für **Physikum (M1)**, **M2** und **M3** einsehen und herunterladen können – sortiert nach Prüfung, Fach und Prüfer.

* **Registrierung nur mit studentischer E-Mail-Adresse.** Das Konto wird erst nach Klick auf einen Bestätigungslink aktiv.
* **Bezahlung über Stripe:** Ein Paket (Standard: 30 €) schaltet alle Protokolle von bis zu 4 Prüfern einer Prüfung frei.
* **Automatische Erstattung:** Lädt jemand nach der Prüfung ein eigenes Protokoll zur gekauften Prüfung hoch, werden automatisch 29 € zurücküberwiesen.
* **Automatische Prüfer-Anlage:** Gibt es einen Prüfer noch nicht, wird er beim Hochladen angelegt (auch bei abweichender Schreibweise wie „Prof. Dr. Müller“ vs. „Müller“ wird er erkannt).
* **Simulationsmodus:** Alles lässt sich ohne Stripe und ohne E-Mail-Server testen. Umschalten im Adminbereich.
* **Umfangreicher Adminbereich** für Prüfungen, Fächer, Prüfer, Protokolle, Freigaben, Import, Nutzer, Zahlungen, Erstattungen, Einstellungen, E-Mail-Postausgang und Logbuch.

---

## Inhalt

1. [Schnellstart zum Ausprobieren](#1-schnellstart-zum-ausprobieren)
2. [Betrieb auf einem Server (Docker)](#2-betrieb-auf-einem-server-docker)
3. [Checkliste vor dem Livegang](#3-checkliste-vor-dem-livegang)
4. [Stripe anbinden](#4-stripe-anbinden)
5. [E-Mail-Versand einrichten](#5-e-mail-versand-einrichten)
6. [Bestehende Protokolle importieren](#6-bestehende-protokolle-importieren)
7. [Der Adminbereich im Überblick](#7-der-adminbereich-im-überblick)
8. [So funktionieren Kauf und Erstattung](#8-so-funktionieren-kauf-und-erstattung)
9. [Backups, Updates, Wartung](#9-backups-updates-wartung)
10. [Für Entwickler](#10-für-entwickler)

---

## 1. Schnellstart zum Ausprobieren

Voraussetzung: Python 3.11 oder neuer.

```bash
git clone <repository-url> protokolldatenbank
cd protokolldatenbank
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

```bash
DEBUG=1 python manage.py migrate
DEBUG=1 python manage.py seed_demo
DEBUG=1 python manage.py runserver
```

Dann <http://localhost:8000> öffnen. Die Beispieldaten enthalten M1, M2 und M3 mit je 3–4 (frei erfundenen) Testprüfern und je zwei Protokollen – eins als Text, eins als PDF.

| Konto | E-Mail | Passwort |
|---|---|---|
| Admin | `admin@uni-beispiel.de` | `Admin123!` |
| Studentin mit M1-Paket (2 Prüfer) | `student@uni-beispiel.de` | `Student123!` |

Zahlungen und E-Mails sind im Simulationsmodus: Statt Stripe erscheint eine Test-Bezahlseite, und Bestätigungslinks werden direkt auf der Seite und im Adminbereich unter **Postausgang** angezeigt. Zum Registrieren eine Adresse wie `irgendwer@uni-beispiel.de` verwenden.

---

## 2. Betrieb auf einem Server (Docker)

Empfohlen wird ein kleiner Linux-Server (z. B. vom Rechenzentrum der Uni oder ein günstiger V-Server) mit Docker.

```bash
cp .env.example .env
nano .env        # SECRET_KEY, SITE_URL, ADMIN_EMAIL, ADMIN_PASSWORD eintragen
```

```bash
docker compose up -d --build
```

Beim Start werden automatisch die Datenbank angelegt, das Admin-Konto aus `ADMIN_EMAIL`/`ADMIN_PASSWORD` erstellt und – wenn `DEMO_DATA=1` – die Beispieldaten geladen. Die Daten (SQLite-Datenbank und hochgeladene Dateien) liegen im Docker-Volume `protokolle-daten`.

Der Container lauscht nur lokal auf Port 8000. Davor gehört ein Webserver mit HTTPS, z. B. **Caddy** (holt sich das Zertifikat automatisch):

```
protokolle.fachschaft-beispiel.de {
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 200MB
    }
}
```

oder **nginx**:

```nginx
server {
    server_name protokolle.fachschaft-beispiel.de;
    client_max_body_size 200m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
    # listen 443 ssl; … (z. B. mit certbot)
}
```

In der `.env` dann `BEHIND_PROXY=1` und `SITE_URL=https://protokolle.fachschaft-beispiel.de` setzen.

**Ohne Docker** geht es genauso: virtuelle Umgebung wie im Schnellstart, `.env` anlegen, dann
`python manage.py migrate`, `python manage.py collectstatic`, `python manage.py ensure_admin` und
`gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 300` (z. B. als systemd-Dienst).

### Wichtige Werte in der `.env`

| Variable | Bedeutung |
|---|---|
| `SECRET_KEY` | Langer Zufallswert, z. B. `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `SITE_URL` | Öffentliche Adresse, z. B. `https://protokolle.fachschaft-beispiel.de` – wird für Links in E-Mails und für die Rückleitung von Stripe gebraucht |
| `DEBUG` | Im Betrieb immer `0` |
| `BEHIND_PROXY` | `1`, wenn ein Webserver (Caddy/nginx) davor HTTPS macht |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Erstes Admin-Konto (wird nur angelegt, wenn es noch nicht existiert) |
| `DEMO_DATA` | `1` = Beispieldaten anlegen, für den echten Betrieb auf `0` setzen |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `SMTP_PASSWORD` | Optional: Geheimnisse als Umgebungsvariable statt im Adminbereich (haben dann Vorrang) |
| `POSTGRES_*` | Optional: PostgreSQL statt SQLite (dann `psycopg[binary]` installieren) |

Alles andere – Preise, Stripe, E-Mail, Texte – wird im Adminbereich eingestellt.

---

## 3. Checkliste vor dem Livegang

Die Übersichtsseite im Adminbereich zeigt offene Punkte automatisch als Hinweise an.

1. **Einstellungen → Registrierung:** eure Uni-Domain(s) eintragen, z. B. `uni-musterstadt.de` (Subdomains wie `stud.uni-musterstadt.de` sind automatisch erlaubt).
2. **Einstellungen → Allgemein:** Name der Fachschaft, Kontaktadresse, Begrüßungstext.
3. **Einstellungen → Rechtliches:** Impressum, Datenschutzerklärung und Nutzungsbedingungen anpassen. Die mitgelieferten Texte sind nur Muster – bitte (z. B. vom AStA/StuRa oder der Rechtsabteilung) prüfen lassen.
4. **Einstellungen → E-Mail:** SMTP einrichten und eine Test-E-Mail schicken (siehe Abschnitt 5).
5. **Einstellungen → Zahlungen:** Stripe anbinden und „Verbindung testen“ (siehe Abschnitt 4).
6. **Prüfungen & Fächer / Prüfer:** Testprüfer und Beispielprotokolle löschen (oder die Datenbank neu aufsetzen ohne `DEMO_DATA`) und den Altbestand importieren (Abschnitt 6).
7. Einmal mit einem echten Studierenden-Konto komplett durchspielen: registrieren, bestätigen, kaufen, hochladen, Erstattung prüfen.

---

## 4. Stripe anbinden

„Einfach den Link einfügen“ reicht bei Stripe leider nicht, weil die Webseite für die automatischen Erstattungen selbst mit Stripe sprechen muss. Ihr braucht dafür **zwei Werte aus eurem Stripe-Konto**, die ihr im Adminbereich einfügt:

1. **Secret Key:** Stripe-Dashboard → *Entwickler* → *API-Schlüssel* → Geheimschlüssel (`sk_live_…`).
   Zum Testen erst den Testschlüssel (`sk_test_…`) nehmen – dann funktionieren Stripes Testkarten wie `4242 4242 4242 4242`.
2. **Webhook-Signaturgeheimnis:** Stripe-Dashboard → *Entwickler* → *Webhooks* → *Endpunkt hinzufügen*.
   Als Adresse die URL eintragen, die im Adminbereich unter **Einstellungen → Zahlungen & Stripe** angezeigt wird (`https://eure-seite.de/zahlung/stripe/webhook/`) und diese Ereignisse auswählen:
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`, `charge.refunded`.
   Danach das Signaturgeheimnis (`whsec_…`) kopieren.
3. Im Adminbereich **Zahlungsmodus → Stripe** wählen, beide Werte eintragen, speichern und **„Verbindung testen“** klicken.

Gut zu wissen:

* Welche Zahlungsarten angeboten werden (Karte, Apple Pay, Google Pay, Klarna …), stellt ihr direkt im Stripe-Dashboard ein.
* Der Webhook sorgt dafür, dass eine Zahlung auch dann verbucht wird, wenn jemand nach dem Bezahlen das Fenster schließt.
* **Gebühren:** Stripe behält bei Erstattungen die Gebühr der ursprünglichen Zahlung ein. Bei 30 € Preis und 29 € Erstattung bleiben pro erstattetem Paket nach Gebühren nur wenige Cent übrig. Preis und Erstattung lassen sich jederzeit anpassen – auch pro Prüfung.
* Schlägt eine Erstattung fehl (z. B. weil die Karte nicht mehr existiert), erscheint sie im Adminbereich unter **Zahlungen** mit einem roten Zähler. Dort kann man es erneut versuchen oder den Betrag anders zurückzahlen und als erledigt markieren. Mit einer Adresse unter *Einstellungen → E-Mail → Benachrichtigungen an* kommt zusätzlich eine E-Mail.
* Zurück in den Testbetrieb: Zahlungsmodus wieder auf **Simulation** stellen.

---

## 5. E-Mail-Versand einrichten

Unter **Einstellungen → E-Mail** den Modus auf **SMTP** stellen und die Zugangsdaten eintragen (bekommt ihr vom Rechenzentrum oder eurem Mail-Anbieter). Typisch: Port 587 mit STARTTLS oder Port 465 mit SSL. Mit **„Test-E-Mail senden“** prüfen.

Alle E-Mails (auch fehlgeschlagene) stehen im **Postausgang** – praktisch, wenn jemand sagt „Ich habe keinen Link bekommen“.

---

## 6. Bestehende Protokolle importieren

Die vorhandene Sammlung so in Ordner sortieren:

```
M1/
  Anatomie/                         ← Fach (optional)
    Prof. Dr. Anna Beispiel/        ← Prüfer
      2024-03-12 Protokoll.pdf
      Herbst 2023.docx
  Biochemie/
    Dr. Max Mustermann/
      Protokoll.txt                 ← .txt wird als Text übernommen
M3/
  Prof. Dr. Erika Musterfrau/
    24.05.2024.pdf
```

* Die erste Ebene ist die Prüfung (Kürzel oder Name, z. B. `M1` oder `Physikum (M1)`).
* Fehlende Prüfer und Fächer werden automatisch angelegt; ähnliche Schreibweisen werden zusammengeführt.
* Ein Datum im Dateinamen wird erkannt (`2024-03-12`, `12.03.2024`, `Herbst 2023`, `WiSe 23/24` …).
* Bereits importierte Dateien werden beim erneuten Import übersprungen – ihr könnt also gefahrlos mehrmals importieren.

**Über den Adminbereich:** Ordner als ZIP packen und unter **Import Altbestand** hochladen. Mit „Nur testen“ seht ihr vorher, was passieren würde.

**Sehr große Sammlungen** direkt auf dem Server importieren:

```bash
python manage.py import_protocols /pfad/zum/ordner --dry-run
python manage.py import_protocols /pfad/zum/ordner
```

Mit Docker den Ordner in `docker-compose.yml` einbinden (`./altbestand:/import:ro`) und dann:

```bash
docker compose exec web python manage.py import_protocols /import
```

Nach dem Import unter **Prüfer** mit dem Filter „Durch Upload angelegt“ bzw. per Suche nach Dubletten schauen und sie mit **Zusammenführen** bereinigen.

---

## 7. Der Adminbereich im Überblick

Erreichbar über **Verwaltung** in der Kopfzeile (nur für Admin-Konten).

| Bereich | Was man dort tun kann |
|---|---|
| **Übersicht** | Kennzahlen (Nutzer, Pakete, Einnahmen, Erstattungen, offene Freigaben), Hinweise auf fehlende Einstellungen, neueste Käufe/Uploads, Logbuch |
| **Prüfungen & Fächer** | Prüfungen anlegen, umbenennen, deaktivieren; Fächer verwalten; abweichende Preise/Erstattungen/Prüferzahl pro Prüfung |
| **Prüfer** | Anlegen, bearbeiten, deaktivieren, Hinweise für Studierende hinterlegen, Dubletten **zusammenführen**, sehen wer welchen Prüfer freigeschaltet hat |
| **Protokolle** | Suchen, filtern, bearbeiten, Datei ersetzen, neue Protokolle anlegen, Sammelaktionen (veröffentlichen, löschen) |
| **Freigaben** | Nur relevant, wenn „Uploads vor Veröffentlichung prüfen“ eingeschaltet ist: Uploads mit Vorschau freigeben (löst Erstattung aus) oder mit Begründung ablehnen |
| **Import Altbestand** | ZIP-Import mit Testlauf und Bericht |
| **Nutzer** | Suchen, E-Mail manuell bestätigen, Bestätigungs-/Passwort-Link schicken, sperren, Admin-Rechte vergeben, Konto löschen, **Paket manuell freischalten** (z. B. bei Barzahlung oder Kulanz), weitere Admins einladen |
| **Zahlungen** | Alle Pakete mit Status, Summen, **CSV-Export** für die Kasse; je Paket: als bezahlt markieren, Erstattung auslösen/wiederholen, manuell erledigte Erstattung abhaken, Zugriff entziehen/wiederherstellen, vollständig erstatten, Prüfer und Zugriffsdauer ändern |
| **Einstellungen** | Name, Texte, Hinweisbanner, erlaubte Domains, Registrierung an/aus, Preis, Erstattung, max. Prüfer, Zugriffsdauer, Stripe, Widerrufs-Hinweis, Moderation, Dateitypen/-größe, Wasserzeichen, E-Mail, Impressum, Datenschutz, Nutzungsbedingungen |
| **Postausgang** | Alle versendeten bzw. simulierten E-Mails |
| **Logbuch** | Wer hat wann was gemacht – alle Zahlungen, Erstattungen, Uploads und Admin-Aktionen |
| **Expertenmodus** | Direkter Zugriff auf alle Rohdaten (nur für Superuser, mit Vorsicht benutzen) |

---

## 8. So funktionieren Kauf und Erstattung

1. Studierende wählen auf der Prüfungsseite bis zu 4 Prüfer (Anzahl einstellbar) und kommen zur Bestellübersicht. Dort bestätigen sie die Nutzungsbedingungen und den Hinweis zum Widerrufsrecht bei digitalen Inhalten.
2. Bezahlt wird bei Stripe (bzw. auf der Test-Bezahlseite). Danach sind alle veröffentlichten – und künftig hinzukommenden – Protokolle dieser Prüfer freigeschaltet.
3. Wurden weniger als 4 Prüfer gewählt, können die freien Plätze später **kostenlos** aufgefüllt werden.
4. Nach der Prüfung lädt die Person ihr Protokoll hoch – pro Prüfer ein Abschnitt, als Text oder Datei. Neue Prüfer werden automatisch angelegt.
5. Sobald das Protokoll veröffentlicht ist (sofort oder nach Freigabe), erstattet die Seite **einmal pro Paket** den eingestellten Betrag über Stripe und schickt eine Bestätigung per E-Mail. Erstattet wird nur ein Paket derselben Prüfung.

**Missbrauchsschutz:** Für Text-Protokolle gilt eine Mindestlänge, Dateien werden auf ihren tatsächlichen Typ geprüft, und pro Paket gibt es nur eine Erstattung. Wenn jemand versucht, mit unbrauchbaren Uploads an die Erstattung zu kommen, schaltet **Einstellungen → Uploads → „Uploads vor Veröffentlichung prüfen“** ein – dann wird erst nach eurer Freigabe veröffentlicht und erstattet.

**Weitergabeschutz:** Heruntergeladene PDFs erhalten auf jeder Seite eine Kennzeichnung mit der E-Mail-Adresse des Käufers (abschaltbar). Protokolldateien liegen außerhalb des öffentlichen Webverzeichnisses und werden nur nach Prüfung der Berechtigung ausgeliefert.

---

## 9. Backups, Updates, Wartung

**Backup:** Alles Wichtige liegt in `DATA_DIR` (Docker: Volume `protokolle-daten`) – die Datenbank `db.sqlite3` und der Ordner `uploads/`. Diesen Ordner regelmäßig sichern, z. B.:

```bash
docker run --rm -v protokolldatenbank_protokolle-daten:/data -v "$PWD":/backup alpine \
  tar czf /backup/protokolle-$(date +%F).tar.gz -C /data .
```

**Update** auf eine neue Version:

```bash
git pull
docker compose up -d --build
```

Datenbankänderungen werden beim Start automatisch übernommen.

**Neues Admin-Konto** auf der Kommandozeile:

```bash
docker compose exec web python manage.py ensure_admin --email neu@uni-beispiel.de --password 'SicheresPasswort!'
```

---

## 10. Für Entwickler

* Django 5.2 (LTS), SQLite (optional PostgreSQL), offizielles Stripe-SDK, pypdf, WhiteNoise, Gunicorn. Kein Build-Schritt für CSS/JS, keine externen Schriftarten oder CDNs (DSGVO).
* Apps: `accounts` (Konten), `protocols` (Prüfungen, Prüfer, Protokolle, Upload, Download, Import), `payments` (Pakete, Stripe, Erstattungen), `verwaltung` (Adminbereich), `core` (Einstellungen, E-Mail, Logbuch, PDF, Startseite).
* Tests: `python manage.py test` (u. a. kompletter Kauf- und Erstattungsablauf, Stripe-Webhooks mit Signaturprüfung, Zugriffsschutz, Import, Adminseiten). Die Stripe-Anbindung wird zusätzlich gegen einen lokalen Fake-Server mit dem echten SDK getestet.
* Entwicklungsserver mit `DEBUG=1 python manage.py runserver`.
