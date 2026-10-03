# IR-Heizung

Ein Thermostat für Home Assistant, gebaut für Infrarot-Panels und andere Heizungen, die nur ein- und ausgeschaltet werden. Es regelt per PID und taktet die Schalter. Den Sollwert wählt es selbst:

| Betriebsart | Wann | Ziel (Standard) |
|---|---|---|
| **Eco** | immer, wenn nichts anderes gilt | 16 °C |
| **Komfort** | per Knopf, für eine feste Dauer (Standard 3 h, spätestens 23 Uhr) | 20 °C |
| **Manuell** | eine von Hand gesetzte Temperatur, gleiche Dauer wie Komfort | frei |
| **PV-Boost** | Einspeisung ab 800 W seit 10 min, Auto lädt nicht | 22 °C |
| **Sommerpause** | Außentemperatur-Mittel über der Heizgrenze | heizt nicht |
| **Sensorfehler** | Raumsensor meldet seit 3 h nichts | heizt nicht |
| **Aus** | Thermostat ausgeschaltet | heizt nicht |

Komfort und Manuell enden von selbst, danach übernimmt wieder die Automatik. PV-Überschuss hebt das Ziel nur an und senkt es nie.

## Installation

1. HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories → `https://github.com/tatec22/ha-ir-heizung` mit der Kategorie *Integration* hinzufügen.
2. **IR-Heizung** herunterladen und Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen → IR-Heizung**: Name, Schalter und Raumsensor wählen.
4. Unter **Konfigurieren** Temperaturen, Komfort, PV-Boost, Heizgrenze und Regler einstellen.

## Was angelegt wird

- **Thermostat** (`climate`) mit Heizen/Aus und den Presets Automatik, Komfort und Manuell.
- **Betriebsart**: zeigt, warum gerade geheizt wird oder warum nicht.
- **Stellwert**: Heizleistung in Prozent.
- **PV-Boost**: an oder aus.
- **Komfort starten** und **Zurück auf Automatik** (Knöpfe).
- **Außentemperatur Mittel** (Diagnose).

## Regelung

- **PID** mit Ausgang 0–100 %.
  - P wirkt auf die Abweichung, D auf die gemessene Temperaturänderung.
  - I summiert nur, solange der Ausgang nicht anschlägt. Ein voll laufendes Panel türmt also keinen Integralwert auf.
- **Takten** in einem festen Zeitfenster (Standard 15 min). Kürzere Phasen als die Mindestlaufzeit oder -pause werden gestreckt statt abgeschnitten.
- Alle gewählten Schalter laufen gemeinsam.

## Sicherheit

- **Sensor ausgefallen:** Meldet der Raumsensor zu lange nichts, schaltet das Thermostat die Heizungen aus. Gezählt wird jede Meldung, auch mit unverändertem Wert.
- **Ausschalten oder Entladen** der Integration schaltet die Heizungen ebenfalls ab.
- **Absicherung am Schalter:** Der Einschaltbefehl wird regelmäßig wiederholt (Standard alle 5 min). Hat der Schalter einen eigenen Auto-Aus-Timer, etwa 30 min, geht die Heizung damit nur aus, wenn Home Assistant ausfällt. Schaltet der Timer doch einmal ab, heizt das Thermostat sofort weiter, ohne die Mindestpause abzuwarten.
- **Fremde Eingriffe:** Wer einen Schalter von Hand umlegt, wird beim nächsten Takt (spätestens nach 30 s) überstimmt. Die Heizungen gehören dem Thermostat.

## Hinweise zu Infrarot

Infrarot erwärmt Flächen und Personen, nicht in erster Linie die Luft. Der Raumsensor gehört deshalb **nicht in den Strahlungsbereich der Panels und nicht in die Sonne**. Sonst misst er zu hoch und das Thermostat schaltet zu früh ab.

## PV-Boost

Die Vorzeichen sind wie bei evcc: Netzleistung positiv heißt Bezug, Akkuleistung positiv heißt Entladung.

- **Start:** Einspeisung über der Startschwelle, so lange wie die Startdauer verlangt, und der Akku entlädt nicht. Weil erst eingespeist wird, wenn der Akku voll ist, kommt der Akku automatisch zuerst.
- **Ende:** Bezug aus Netz und Akku zusammen über der Stoppschwelle für die Stoppdauer, oder das Auto beginnt zu laden.

## Entwicklung

```bash
python -m venv .venv
.venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```

Unter Windows mit `pytest -p no:homeassistant`. Das `conftest.py` im Hauptordner bringt die Testumgebung dort zum Laufen.

## Herkunft

Die Grundidee (PID mit zeitproportionalem Schalten) stammt aus [ScratMan/HASmartThermostat](https://github.com/ScratMan/HASmartThermostat) und dessen Fork [Wheemer/HASmartThermostat](https://github.com/Wheemer/HASmartThermostat), beide unter MIT-Lizenz. Diese Integration ist eine schlanke Neufassung für genau einen Zweck: Heizen mit Schaltern, mit Komfortzeiten, PV-Boost und Heizgrenze. Kühlen, Ventile, Autotune und lernende Regler gibt es hier nicht.
