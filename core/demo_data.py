"""Beispieldaten: drei Prüfungen mit fiktiven Testprüfern und je zwei Protokollen.

Alle Namen sind frei erfunden.
"""

EXAMS = [
    {
        "code": "M1",
        "name": "Physikum (M1)",
        "description": "Mündlich-praktischer Teil des Ersten Abschnitts der Ärztlichen Prüfung.",
        "subjects": ["Anatomie", "Biochemie", "Physiologie"],
        "examiners": [
            {
                "name": "Prof. Dr. Anna Beispiel",
                "subject": "Anatomie",
                "institute": "Institut für Anatomie",
                "description": "Prüft am Präparat und fragt gerne vom Präparat in die Klinik.",
                "protocols": [
                    ("2025-08-26", "2", """Prüfung am Präparat, ca. 25 Minuten pro Prüfling. Die Atmosphäre war sehr freundlich, Prof. Beispiel hilft weiter, wenn man hängt.

Fragen an mich:
1. Plexus brachialis am Präparat zeigen: Faszikel benennen (lateral, medial, posterior) und welche Nerven daraus hervorgehen.
   → N. musculocutaneus, N. medianus (Medianusgabel), N. ulnaris, N. radialis, N. axillaris.
2. Klinik: Was passiert bei einer Läsion des N. radialis im Sulcus nervi radialis?
   → Fallhand, Sensibilitätsausfall am Handrücken (Spatium interosseum I), M. triceps meist intakt.
3. Koronararterien am Präparat zeigen und die Versorgungstypen erklären (Rechts-, Links-, ausgeglichener Typ).
4. Embryologie: Entwicklung des Herzschlauchs, Septierung der Vorhöfe (Septum primum und secundum, Foramen ovale).

Fragen an meine Mitprüflinge:
- Leistenkanal: Wände, Inhalt bei Mann und Frau, direkte vs. indirekte Leistenhernie.
- Histologie: Leber (Zentralvene, Glisson-Trias, Leberläppchen-Konzepte).

Tipp: Den Präparierkurs gut wiederholen – sie möchte, dass man die Strukturen sicher findet."""),
                    ("2025-03-12", "1", """Themen der Prüfung:
- Schädelbasis: Foramina und was hindurchtritt (Foramen ovale → N. mandibularis, Foramen rotundum → N. maxillaris, Foramen jugulare → IX, X, XI und V. jugularis interna).
- Hirnnerven: Verlauf des N. facialis, Unterschied zwischen zentraler und peripherer Fazialisparese (Stirnast!).
- Histologie: Niere – Nephron, juxtaglomerulärer Apparat, Macula densa.
- Kniegelenk: Bänder, Menisken, „Unhappy Triad“.

Sie lässt einen erst frei erzählen und hakt dann gezielt nach. Wer strukturiert antwortet, hat es leicht."""),
                ],
            },
            {
                "name": "Dr. Lukas Probe",
                "subject": "Anatomie",
                "institute": "Institut für Anatomie – Neuroanatomie",
                "description": "Schwerpunkt Neuroanatomie, sehr ruhige Prüfungsatmosphäre.",
                "protocols": [
                    ("2025-08-26", "2", """- Rückenmark im Querschnitt: Hinterstrangbahn, Tractus spinothalamicus, Pyramidenbahn – und wo kreuzen sie?
- Brown-Séquard-Syndrom: Ausfälle ipsi- und kontralateral erklären.
- Basalganglien: direkter und indirekter Weg, Pathophysiologie des Morbus Parkinson.
- Am Hirnpräparat die Capsula interna zeigen; Blutversorgung (A. cerebri media, Aa. lenticulostriatae).

Er gibt viel Zeit zum Nachdenken und formuliert Fragen gerne um, wenn man nicht sofort versteht, worauf er hinaus will."""),
                    ("2025-03-11", "2", """- Hirnnervenkerne im Hirnstamm, Okulomotorik (III, IV, VI) und typische Ausfälle.
- Liquorräume und Liquorzirkulation, Hydrocephalus occlusus vs. communicans.
- Limbisches System: Papez-Kreis.
- Histologie: Kleinhirnrinde (Purkinje-Zellen, Körnerzellen, Kletter- und Moosfasern).

Bilder aus dem Atlas mitbringen lohnt sich nicht – er arbeitet nur mit Präparaten und Skizzen an der Tafel."""),
                ],
            },
            {
                "name": "Prof. Dr. Max Mustermann",
                "subject": "Biochemie",
                "institute": "Institut für Biochemie",
                "description": "Lässt gerne Strukturformeln zeichnen und fragt nach klinischem Bezug.",
                "protocols": [
                    ("2025-08-27", "2", """1. Glykolyse: Schlüsselenzyme und ihre Regulation (Hexokinase/Glucokinase, PFK-1 mit Fructose-2,6-bisphosphat, Pyruvatkinase).
2. Warum bekommen Patienten mit Pyruvatkinase-Mangel eine hämolytische Anämie?
   → Erythrozyten sind auf die Glykolyse angewiesen; ATP-Mangel führt zu Membranschäden.
3. Harnstoffzyklus: Ort (Mitochondrium und Zytosol der Hepatozyten), Schlüsselenzym Carbamoylphosphat-Synthetase I, Aktivator N-Acetylglutamat.
4. Hyperammonämie: Symptome und warum Ammoniak neurotoxisch ist.

Streng, aber fair. Wer nicht weiterweiß, bekommt Stichworte. Strukturformel von Glucose und ATP sicher können!"""),
                    ("2024-09-03", "2", """- Cholesterinbiosynthese: HMG-CoA-Reduktase, Regulation, Wirkprinzip der Statine.
- Lipoproteine: Chylomikronen, VLDL, LDL, HDL – Funktion und Apolipoproteine.
- Familiäre Hypercholesterinämie: Defekt des LDL-Rezeptors.
- DNA-Replikation: Okazaki-Fragmente, Telomerase.
- Zum Schluss: Vitamin-B12-Mangel – welche Enzyme sind betroffen (Methylmalonyl-CoA-Mutase, Methionin-Synthase)?"""),
                ],
            },
            {
                "name": "Prof. Dr. Erika Musterfrau",
                "subject": "Physiologie",
                "institute": "Institut für Physiologie",
                "description": "Lässt viel zeichnen – Arbeitsdiagramm und Druck-Volumen-Kurven üben!",
                "protocols": [
                    ("2025-03-13", "1", """- Aktionspotenzial am Herzen: Phasen des Arbeitsmyokard-AP, beteiligte Ionenströme, Plateauphase durch L-Typ-Calciumkanäle.
- EKG: Was entspricht P-Welle, QRS-Komplex und T-Welle? Lagetyp an einem Beispiel-EKG bestimmen.
- Frank-Starling-Mechanismus im Arbeitsdiagramm einzeichnen (Vorlast- und Nachlasterhöhung).
- Niere: Clearance-Begriff, GFR-Bestimmung mit Inulin bzw. Kreatinin.

Sie lässt viel an der Tafel zeichnen – das Arbeitsdiagramm des Herzens unbedingt vorher üben."""),
                    ("2024-08-28", "3", """- Atmung: Compliance, Surfactant, Atemarbeit.
- Sauerstoffbindungskurve: Rechtsverschiebung (CO2, H+, Temperatur, 2,3-BPG), Bohr-Effekt.
- Säure-Basen-Haushalt: Interpretation einer BGA (metabolische Azidose mit respiratorischer Kompensation).
- Sinnesphysiologie: Hörbahn, Frequenzdispersion in der Cochlea (Wanderwelle)."""),
                ],
            },
        ],
    },
    {
        "code": "M2",
        "name": "Zweiter Abschnitt (M2)",
        "description": "Gedächtnisprotokolle zum Zweiten Abschnitt der Ärztlichen Prüfung.",
        "subjects": ["Innere Medizin", "Chirurgie", "Neurologie"],
        "examiners": [
            {
                "name": "Prof. Dr. Clara Testfall",
                "subject": "Innere Medizin",
                "institute": "Medizinische Klinik I",
                "description": "Fallbasierte Fragen, legt Wert auf eine strukturierte Differenzialdiagnostik.",
                "protocols": [
                    ("2025-04-10", "2", """Fall: Ein 67-jähriger Patient kommt mit akuter Luftnot und Beinödemen.
- Differenzialdiagnosen: kardiale Dekompensation, Lungenembolie, Pneumonie, COPD-Exazerbation.
- Diagnostik: Labor (NT-proBNP, Troponin, D-Dimere), EKG, Röntgen-Thorax, Echokardiografie.
- Therapie der akuten Herzinsuffizienz: Oberkörperhochlagerung, Sauerstoff bei Hypoxämie, Schleifendiuretika, ggf. Nitrate.
- Langzeittherapie HFrEF: ACE-Hemmer bzw. ARNI, Betablocker, MRA, SGLT2-Inhibitor."""),
                    ("2024-10-15", "1", """- Diabetes mellitus Typ 2: Diagnosekriterien (HbA1c ≥ 6,5 %, Nüchternglukose ≥ 126 mg/dl) und Stufentherapie.
- Diabetische Ketoazidose vs. hyperosmolares hyperglykämisches Syndrom.
- Schilddrüse: Ursachen einer Hyperthyreose, Morbus Basedow (endokrine Orbitopathie, TRAK).
- Anämie-Abklärung anhand des MCV."""),
                ],
            },
            {
                "name": "Prof. Dr. Paul Platzhalter",
                "subject": "Chirurgie",
                "institute": "Klinik für Allgemein- und Viszeralchirurgie",
                "description": "",
                "protocols": [
                    ("2025-04-11", "2", """- Akutes Abdomen: Vorgehen und typische Ursachen nach Lokalisation.
- Appendizitis: klinische Zeichen (McBurney, Lanz, Blumberg, Rovsing, Psoas-Zeichen), Alvarado-Score, Therapie.
- Ileus: mechanisch vs. paralytisch, Röntgenbefund (Spiegelbildung), Therapie.
- Postoperative Komplikationen: Woran denkt man bei Fieber am 5. Tag nach Darmresektion? → Anastomoseninsuffizienz."""),
                    ("2024-10-16", "3", """- Frakturlehre: sichere und unsichere Frakturzeichen, Prinzip der AO-Klassifikation.
- Distale Radiusfraktur: Extensions- vs. Flexionsfraktur (Colles/Smith), Therapie.
- Polytrauma: Vorgehen nach dem ABCDE-Schema.
- Cholezystolithiasis: Symptome, Murphy-Zeichen, Therapie (frühelektive Cholezystektomie)."""),
                ],
            },
            {
                "name": "PD Dr. Mia Vorlage",
                "subject": "Neurologie",
                "institute": "Klinik für Neurologie",
                "description": "Fragt gerne nach Leitlinien und Zeitfenstern.",
                "protocols": [
                    ("2025-04-10", "1", """- Schlaganfall: Symptome, Zeitfenster für Lyse und Thrombektomie, NIHSS.
- Ischämischer vs. hämorrhagischer Infarkt in der nativen CT.
- Sekundärprophylaxe: Thrombozytenaggregationshemmung, bei Vorhofflimmern orale Antikoagulation.
- Status epilepticus: Stufentherapie (Benzodiazepine, dann z. B. Levetiracetam)."""),
                    ("2024-10-14", "2", """- Multiple Sklerose: Diagnosekriterien (räumliche und zeitliche Dissemination), Liquorbefund (oligoklonale Banden).
- Kopfschmerz: Migräne vs. Spannungskopfschmerz vs. Clusterkopfschmerz.
- Bakterielle Meningitis: Klinik, Meningismuszeichen, kalkulierte Therapie.
- Parkinson-Syndrom: Kardinalsymptome und Therapieprinzipien."""),
                ],
            },
        ],
    },
    {
        "code": "M3",
        "name": "Dritter Abschnitt (M3)",
        "description": "Mündlich-praktische Prüfung am Ende des Praktischen Jahres.",
        "subjects": ["Innere Medizin", "Chirurgie", "Wahlfach"],
        "examiners": [
            {
                "name": "Prof. Dr. Thomas Fiktiv",
                "subject": "Innere Medizin",
                "institute": "Medizinische Klinik II – Gastroenterologie",
                "description": "Möchte eine saubere, strukturierte Fallvorstellung hören.",
                "protocols": [
                    ("2025-05-20", "1", """Tag 1 am Patientenbett: Anamnese und körperliche Untersuchung eines Patienten mit Leberzirrhose, anschließend Fallvorstellung vor der Kommission.

Tag 2, Theorie:
- Leberzirrhose: Child-Pugh-Score, Komplikationen (Aszites, Varizenblutung, hepatische Enzephalopathie).
- Akute Varizenblutung: Kreislaufstabilisierung, Terlipressin, Antibiotikaprophylaxe, endoskopische Ligatur.
- Spontan bakterielle Peritonitis: Diagnose (mehr als 250 neutrophile Granulozyten/µl im Aszites) und Therapie.
- EKG-Befundung: Vorhofflimmern, CHA2DS2-VASc-Score."""),
                    ("2024-11-19", "2", """- Patient mit COPD-Exazerbation: Untersuchungsbefund vorgestellt.
- GOLD-Klassifikation und Therapie, Indikation für eine Langzeit-Sauerstofftherapie.
- Pneumonie: CRB-65, kalkulierte Antibiose ambulant vs. stationär.
- Akutes Nierenversagen: prä-, intra-, postrenal; Notfallindikationen zur Dialyse."""),
                ],
            },
            {
                "name": "Prof. Dr. Sarah Exempel",
                "subject": "Chirurgie",
                "institute": "Klinik für Allgemein-, Viszeral- und Gefäßchirurgie",
                "description": "",
                "protocols": [
                    ("2025-05-21", "2", """- Patientin nach Hemithyreoidektomie: mögliche Komplikationen (Rekurrensparese, Hypokalzämie, Nachblutung).
- Schilddrüsenknoten: Abklärung (Sonografie, TSH, Szintigrafie, Feinnadelpunktion).
- Kolorektales Karzinom: Staging, TNM, Therapie beim Rektumkarzinom (neoadjuvante Radiochemotherapie).
- Leistenhernie: OP-Verfahren (Lichtenstein, TAPP, TEP)."""),
                    ("2024-11-20", "2", """- Wundheilung und Wundheilungsstörungen, Einteilung von Wunden.
- Akute Pankreatitis: Ursachen (Gallensteine, Alkohol), Diagnostik (Lipase), Therapie (Volumen!).
- Periphere arterielle Verschlusskrankheit: Fontaine-Stadien, Knöchel-Arm-Index.
- Am Patientenbett: Untersuchung des Abdomens bei Narbenhernie."""),
                ],
            },
            {
                "name": "Dr. Felix Dummy",
                "subject": "Wahlfach",
                "institute": "Klinik für Anästhesiologie",
                "description": "Wahlfach Anästhesiologie.",
                "protocols": [
                    ("2025-05-20", "1", """- Narkoseeinleitung: Medikamente (Hypnotikum, Opioid, Muskelrelaxans), Rapid Sequence Induction – wann und wie?
- Atemwegsmanagement: schwieriger Atemweg, Mallampati-Klassifikation.
- Maligne Hyperthermie: Klinik und Therapie mit Dantrolen.
- Reanimation nach ERC-Leitlinie bei Erwachsenen: Adrenalin- und Amiodarongabe."""),
                    ("2024-11-19", "2", """- Präoperative Risikoeinschätzung: ASA-Klassifikation, Nüchternheitsregeln.
- Regionalanästhesie: Spinal- vs. Periduralanästhesie, Kontraindikationen.
- Schock: Formen und Therapie, Katecholamine.
- Sepsis: qSOFA und die Maßnahmen der ersten Stunde."""),
                ],
            },
            {
                "name": "Prof. Dr. Laura Entwurf",
                "subject": "Wahlfach",
                "institute": "Klinik für Kinder- und Jugendmedizin",
                "description": "Wahlfach Pädiatrie.",
                "protocols": [
                    ("2025-05-22", "1", """- Neugeborenen-Untersuchung: U1/U2, APGAR-Score.
- Ikterus neonatorum: physiologisch vs. pathologisch, Indikation zur Phototherapie.
- Fieberkrampf: einfach vs. komplex, Vorgehen.
- Impfkalender der STIKO: Grundimmunisierung im ersten Lebensjahr."""),
                    ("2024-11-21", "2", """- Kind mit Atemnot und Stridor: Pseudokrupp vs. Epiglottitis.
- Exsikkose bei Gastroenteritis: Einschätzung und orale Rehydratation.
- Kawasaki-Syndrom: Kriterien und Therapie (IVIG, ASS).
- Entwicklungsmeilensteine im ersten Lebensjahr."""),
                ],
            },
        ],
    },
]
