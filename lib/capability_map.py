"""
Maps Solarman YAML sensor definitions to Homey capabilities.
Handles dynamic capability building for all Deye inverter models.
"""

import re


_CAPABILITY_TITLES: dict[str, dict[str, str]] = {
    'AC Output Power': {
        'en': 'AC Output Power', 'da': 'AC Udgangseffekt', 'de': 'AC-Ausgangsleistung',
        'es': 'Potencia de Salida CA', 'fr': 'Puissance de Sortie CA', 'it': 'Potenza Uscita CA',
        'nl': 'AC-uitgangsvermogen', 'no': 'AC Utgangseffekt', 'pl': 'Moc Wyjściowa AC',
        'sv': 'AC-utgångseffekt',
    },
    'Battery Charged Energy': {
        'en': 'Battery Charged Energy', 'da': 'Batteriopladet Energi', 'de': 'Batterie-Ladeenergie',
        'es': 'Energía de Carga de Batería', 'fr': "Énergie de Charge Batterie", 'it': 'Energia di Carica Batteria',
        'nl': 'Batterij Laadenergie', 'no': 'Batteriladet Energi', 'pl': 'Energia Naładowana Baterii',
        'sv': 'Batteriladdad Energi',
    },
    'Battery Current': {
        'en': 'Battery Current', 'da': 'Batteristrøm', 'de': 'Batteriestrom',
        'es': 'Corriente de Batería', 'fr': 'Courant Batterie', 'it': 'Corrente Batteria',
        'nl': 'Batterijstroom', 'no': 'Batteristrøm', 'pl': 'Prąd Baterii',
        'sv': 'Batteriström',
    },
    'Battery Discharged Energy': {
        'en': 'Battery Discharged Energy', 'da': 'Batteriafladet Energi', 'de': 'Batterie-Entladeenergie',
        'es': 'Energía de Descarga de Batería', 'fr': 'Énergie de Décharge Batterie', 'it': 'Energia di Scarica Batteria',
        'nl': 'Batterij Ontlaadenergie', 'no': 'Batteriutladet Energi', 'pl': 'Energia Rozładowana Baterii',
        'sv': 'Batteriurladdad Energi',
    },
    'Battery SOC': {
        'en': 'Battery SOC', 'da': 'Batteri SOC', 'de': 'Batterie-Ladezustand',
        'es': 'Estado de Carga', 'fr': 'État de Charge', 'it': 'Stato di Carica',
        'nl': 'Batterij Laadstatus', 'no': 'Batteri Ladenivå', 'pl': 'Stan Naładowania',
        'sv': 'Batteriets Laddstatus',
    },
    'Battery Status': {
        'en': 'Battery Status', 'da': 'Batteristatus', 'de': 'Batteriestatus',
        'es': 'Estado de Batería', 'fr': 'État Batterie', 'it': 'Stato Batteria',
        'nl': 'Batterijstatus', 'no': 'Batteristatus', 'pl': 'Status Baterii',
        'sv': 'Batteristatus',
    },
    'Battery Temperature': {
        'en': 'Battery Temperature', 'da': 'Batteritemperatur', 'de': 'Batterietemperatur',
        'es': 'Temperatura de Batería', 'fr': 'Température Batterie', 'it': 'Temperatura Batteria',
        'nl': 'Batterijtemperatuur', 'no': 'Batteritemperatur', 'pl': 'Temperatura Baterii',
        'sv': 'Batteritemperatur',
    },
    'Battery Voltage': {
        'en': 'Battery Voltage', 'da': 'Batterispænding', 'de': 'Batteriespannung',
        'es': 'Voltaje de Batería', 'fr': 'Tension Batterie', 'it': 'Tensione Batteria',
        'nl': 'Batterijspanning', 'no': 'Batterispenning', 'pl': 'Napięcie Baterii',
        'sv': 'Batterispänning',
    },
    'Daily Production': {
        'en': 'Daily Production', 'da': 'Daglig Produktion', 'de': 'Tagesproduktion',
        'es': 'Producción Diaria', 'fr': 'Production Journalière', 'it': 'Produzione Giornaliera',
        'nl': 'Dagelijkse Productie', 'no': 'Daglig Produksjon', 'pl': 'Produkcja Dzienna',
        'sv': 'Daglig Produktion',
    },
    'Fault / Alarm': {
        'en': 'Fault / Alarm', 'da': 'Fejl / Alarm', 'de': 'Fehler / Alarm',
        'es': 'Falla / Alarma', 'fr': 'Défaut / Alarme', 'it': 'Guasto / Allarme',
        'nl': 'Storing / Alarm', 'no': 'Feil / Alarm', 'pl': 'Usterka / Alarm',
        'sv': 'Fel / Larm',
    },
    'Grid Current': {
        'en': 'Grid Current', 'da': 'Netstrøm', 'de': 'Netzstrom',
        'es': 'Corriente de Red', 'fr': 'Courant Réseau', 'it': 'Corrente di Rete',
        'nl': 'Netstroom', 'no': 'Nettstrøm', 'pl': 'Prąd Sieci',
        'sv': 'Nätström',
    },
    'Grid Export Energy': {
        'en': 'Grid Export Energy', 'da': 'Nettilbageført Energi', 'de': 'Netzeinspeiseenergie',
        'es': 'Energía Exportada a Red', 'fr': "Énergie Exportée Réseau", 'it': 'Energia Esportata in Rete',
        'nl': 'Teruggeleverde Energie', 'no': 'Eksportert Nettenergi', 'pl': 'Energia Eksportowana do Sieci',
        'sv': 'Exporterad Nätenergi',
    },
    'Grid Frequency': {
        'en': 'Grid Frequency', 'da': 'Netfrekvens', 'de': 'Netzfrequenz',
        'es': 'Frecuencia de Red', 'fr': 'Fréquence Réseau', 'it': 'Frequenza di Rete',
        'nl': 'Netfrequentie', 'no': 'Nettfrekvens', 'pl': 'Częstotliwość Sieci',
        'sv': 'Nätfrekvens',
    },
    'Grid Import Energy': {
        'en': 'Grid Import Energy', 'da': 'Nettrukket Energi', 'de': 'Netzbezugsenergie',
        'es': 'Energía Importada de Red', 'fr': 'Énergie Importée Réseau', 'it': 'Energia Importata da Rete',
        'nl': 'Afgenomen Energie', 'no': 'Importert Nettenergi', 'pl': 'Energia Importowana z Sieci',
        'sv': 'Importerad Nätenergi',
    },
    'Grid Power': {
        'en': 'Grid Power', 'da': 'Neteffekt', 'de': 'Netzleistung',
        'es': 'Potencia de Red', 'fr': 'Puissance Réseau', 'it': 'Potenza di Rete',
        'nl': 'Netvermogen', 'no': 'Netteffekt', 'pl': 'Moc Sieci',
        'sv': 'Näteffekt',
    },
    'Grid Power (Live)': {
        'en': 'Grid Power (Live)', 'da': 'Neteffekt (Live)', 'de': 'Netzleistung (Live)',
        'es': 'Potencia de Red (en Vivo)', 'fr': 'Puissance Réseau (en Direct)', 'it': 'Potenza di Rete (in Tempo Reale)',
        'nl': 'Netvermogen (Live)', 'no': 'Netteffekt (Live)', 'pl': 'Moc Sieci (na Żywo)',
        'sv': 'Näteffekt (Live)',
    },
    'Grid Voltage': {
        'en': 'Grid Voltage', 'da': 'Netspænding', 'de': 'Netzspannung',
        'es': 'Voltaje de Red', 'fr': 'Tension Réseau', 'it': 'Tensione di Rete',
        'nl': 'Netspanning', 'no': 'Nettspenning', 'pl': 'Napięcie Sieci',
        'sv': 'Nätspänning',
    },
    'L1 Current': {
        'en': 'L1 Current', 'da': 'L1 Strøm', 'de': 'L1 Strom',
        'es': 'Corriente L1', 'fr': 'Courant L1', 'it': 'Corrente L1',
        'nl': 'L1 Stroom', 'no': 'L1 Strøm', 'pl': 'Prąd L1',
        'sv': 'L1 Ström',
    },
    'L1 Voltage': {
        'en': 'L1 Voltage', 'da': 'L1 Spænding', 'de': 'L1 Spannung',
        'es': 'Voltaje L1', 'fr': 'Tension L1', 'it': 'Tensione L1',
        'nl': 'L1 Spanning', 'no': 'L1 Spenning', 'pl': 'Napięcie L1',
        'sv': 'L1 Spänning',
    },
    'L2 Current': {
        'en': 'L2 Current', 'da': 'L2 Strøm', 'de': 'L2 Strom',
        'es': 'Corriente L2', 'fr': 'Courant L2', 'it': 'Corrente L2',
        'nl': 'L2 Stroom', 'no': 'L2 Strøm', 'pl': 'Prąd L2',
        'sv': 'L2 Ström',
    },
    'L2 Voltage': {
        'en': 'L2 Voltage', 'da': 'L2 Spænding', 'de': 'L2 Spannung',
        'es': 'Voltaje L2', 'fr': 'Tension L2', 'it': 'Tensione L2',
        'nl': 'L2 Spanning', 'no': 'L2 Spenning', 'pl': 'Napięcie L2',
        'sv': 'L2 Spänning',
    },
    'L3 Current': {
        'en': 'L3 Current', 'da': 'L3 Strøm', 'de': 'L3 Strom',
        'es': 'Corriente L3', 'fr': 'Courant L3', 'it': 'Corrente L3',
        'nl': 'L3 Stroom', 'no': 'L3 Strøm', 'pl': 'Prąd L3',
        'sv': 'L3 Ström',
    },
    'L3 Voltage': {
        'en': 'L3 Voltage', 'da': 'L3 Spænding', 'de': 'L3 Spannung',
        'es': 'Voltaje L3', 'fr': 'Tension L3', 'it': 'Tensione L3',
        'nl': 'L3 Spanning', 'no': 'L3 Spenning', 'pl': 'Napięcie L3',
        'sv': 'L3 Spänning',
    },
    'Load Power': {
        'en': 'Load Power', 'da': 'Belastningseffekt', 'de': 'Lastleistung',
        'es': 'Potencia de Carga', 'fr': 'Puissance Charge', 'it': 'Potenza di Carico',
        'nl': 'Belastingsvermogen', 'no': 'Belastningseffekt', 'pl': 'Moc Obciążenia',
        'sv': 'Lasteffekt',
    },
    'Micro-inverter Power': {
        'en': 'Micro-inverter Power', 'da': 'Mikroinverter-effekt', 'de': 'Mikrowechselrichter-Leistung',
        'es': 'Potencia de Microinversor', 'fr': 'Puissance Micro-onduleur', 'it': 'Potenza Microinverter',
        'nl': 'Micro-omvormer Vermogen', 'no': 'Mikroinverter-effekt', 'pl': 'Moc Mikroinwertera',
        'sv': 'Mikroväxelriktareffekt',
    },
    'Output Apparent Power': {
        'en': 'Output Apparent Power', 'da': 'Udgangs Skinneffekt', 'de': 'Ausgangsscheinleistung',
        'es': 'Potencia Aparente de Salida', 'fr': 'Puissance Apparente Sortie', 'it': 'Potenza Apparente Uscita',
        'nl': 'Schijnbaar Uitgangsvermogen', 'no': 'Utgangs Skinneffekt', 'pl': 'Moc Pozorna Wyjściowa',
        'sv': 'Skenbar Utgångseffekt',
    },
    'Output Reactive Power': {
        'en': 'Output Reactive Power', 'da': 'Udgangs Reaktiv Effekt', 'de': 'Ausgangsblindleistung',
        'es': 'Potencia Reactiva de Salida', 'fr': 'Puissance Réactive Sortie', 'it': 'Potenza Reattiva Uscita',
        'nl': 'Reactief Uitgangsvermogen', 'no': 'Utgangs Reaktiv Effekt', 'pl': 'Moc Bierna Wyjściowa',
        'sv': 'Reaktiv Utgångseffekt',
    },
    'Power Delivery': {
        'en': 'Power Delivery', 'da': 'Effektafgivelse', 'de': 'Leistungsabgabe',
        'es': 'Potencia de Descarga', 'fr': 'Puissance de Décharge', 'it': 'Potenza di Scarica',
        'nl': 'Vermogensafgifte', 'no': 'Effektavgivelse', 'pl': 'Moc Rozładowania',
        'sv': 'Effektleverans',
    },
    'Power Usage': {
        'en': 'Power Usage', 'da': 'Effektforbrug', 'de': 'Leistungsaufnahme',
        'es': 'Consumo de Potencia', 'fr': 'Consommation Électrique', 'it': 'Consumo di Potenza',
        'nl': 'Vermogensverbruik', 'no': 'Effektforbruk', 'pl': 'Zużycie Mocy',
        'sv': 'Effektförbrukning',
    },
    'PV1 Current': {
        'en': 'PV1 Current', 'da': 'PV1 Strøm', 'de': 'PV1 Strom',
        'es': 'Corriente PV1', 'fr': 'Courant PV1', 'it': 'Corrente FV1',
        'nl': 'PV1 Stroom', 'no': 'PV1 Strøm', 'pl': 'Prąd PV1',
        'sv': 'PV1 Ström',
    },
    'PV1 Power': {
        'en': 'PV1 Power', 'da': 'PV1 Effekt', 'de': 'PV1 Leistung',
        'es': 'Potencia PV1', 'fr': 'Puissance PV1', 'it': 'Potenza FV1',
        'nl': 'PV1 Vermogen', 'no': 'PV1 Effekt', 'pl': 'Moc PV1',
        'sv': 'PV1 Effekt',
    },
    'PV1 Voltage': {
        'en': 'PV1 Voltage', 'da': 'PV1 Spænding', 'de': 'PV1 Spannung',
        'es': 'Voltaje PV1', 'fr': 'Tension PV1', 'it': 'Tensione FV1',
        'nl': 'PV1 Spanning', 'no': 'PV1 Spenning', 'pl': 'Napięcie PV1',
        'sv': 'PV1 Spänning',
    },
    'PV2 Current': {
        'en': 'PV2 Current', 'da': 'PV2 Strøm', 'de': 'PV2 Strom',
        'es': 'Corriente PV2', 'fr': 'Courant PV2', 'it': 'Corrente FV2',
        'nl': 'PV2 Stroom', 'no': 'PV2 Strøm', 'pl': 'Prąd PV2',
        'sv': 'PV2 Ström',
    },
    'PV2 Power': {
        'en': 'PV2 Power', 'da': 'PV2 Effekt', 'de': 'PV2 Leistung',
        'es': 'Potencia PV2', 'fr': 'Puissance PV2', 'it': 'Potenza FV2',
        'nl': 'PV2 Vermogen', 'no': 'PV2 Effekt', 'pl': 'Moc PV2',
        'sv': 'PV2 Effekt',
    },
    'PV2 Voltage': {
        'en': 'PV2 Voltage', 'da': 'PV2 Spænding', 'de': 'PV2 Spannung',
        'es': 'Voltaje PV2', 'fr': 'Tension PV2', 'it': 'Tensione FV2',
        'nl': 'PV2 Spanning', 'no': 'PV2 Spenning', 'pl': 'Napięcie PV2',
        'sv': 'PV2 Spänning',
    },
    'PV3 Current': {
        'en': 'PV3 Current', 'da': 'PV3 Strøm', 'de': 'PV3 Strom',
        'es': 'Corriente PV3', 'fr': 'Courant PV3', 'it': 'Corrente FV3',
        'nl': 'PV3 Stroom', 'no': 'PV3 Strøm', 'pl': 'Prąd PV3',
        'sv': 'PV3 Ström',
    },
    'PV3 Power': {
        'en': 'PV3 Power', 'da': 'PV3 Effekt', 'de': 'PV3 Leistung',
        'es': 'Potencia PV3', 'fr': 'Puissance PV3', 'it': 'Potenza FV3',
        'nl': 'PV3 Vermogen', 'no': 'PV3 Effekt', 'pl': 'Moc PV3',
        'sv': 'PV3 Effekt',
    },
    'PV3 Voltage': {
        'en': 'PV3 Voltage', 'da': 'PV3 Spænding', 'de': 'PV3 Spannung',
        'es': 'Voltaje PV3', 'fr': 'Tension PV3', 'it': 'Tensione FV3',
        'nl': 'PV3 Spanning', 'no': 'PV3 Spenning', 'pl': 'Napięcie PV3',
        'sv': 'PV3 Spänning',
    },
    'PV4 Current': {
        'en': 'PV4 Current', 'da': 'PV4 Strøm', 'de': 'PV4 Strom',
        'es': 'Corriente PV4', 'fr': 'Courant PV4', 'it': 'Corrente FV4',
        'nl': 'PV4 Stroom', 'no': 'PV4 Strøm', 'pl': 'Prąd PV4',
        'sv': 'PV4 Ström',
    },
    'PV4 Power': {
        'en': 'PV4 Power', 'da': 'PV4 Effekt', 'de': 'PV4 Leistung',
        'es': 'Potencia PV4', 'fr': 'Puissance PV4', 'it': 'Potenza FV4',
        'nl': 'PV4 Vermogen', 'no': 'PV4 Effekt', 'pl': 'Moc PV4',
        'sv': 'PV4 Effekt',
    },
    'PV4 Voltage': {
        'en': 'PV4 Voltage', 'da': 'PV4 Spænding', 'de': 'PV4 Spannung',
        'es': 'Voltaje PV4', 'fr': 'Tension PV4', 'it': 'Tensione FV4',
        'nl': 'PV4 Spanning', 'no': 'PV4 Spenning', 'pl': 'Napięcie PV4',
        'sv': 'PV4 Spänning',
    },
    'Radiator Temperature': {
        'en': 'Radiator Temperature', 'da': 'Kølepladetemperatur', 'de': 'Kühlkörpertemperatur',
        'es': 'Temperatura del Radiador', 'fr': 'Température Radiateur', 'it': 'Temperatura Radiatore',
        'nl': 'Radiatortemperatuur', 'no': 'Kjøleribbetemperatur', 'pl': 'Temperatura Radiatora',
        'sv': 'Kylflänstemperatur',
    },
    'Solar Power (DC Input)': {
        'en': 'Solar Power (DC Input)', 'da': 'Solenergi (DC Input)', 'de': 'Solarleistung (DC-Eingang)',
        'es': 'Potencia Solar (Entrada CC)', 'fr': 'Puissance Solaire (Entrée CC)', 'it': 'Potenza Solare (Ingresso CC)',
        'nl': 'Zonne-energie (DC-ingang)', 'no': 'Solenergi (DC-inngang)', 'pl': 'Moc Solarna (Wejście DC)',
        'sv': 'Solenergi (DC-ingång)',
    },
    'Temperature': {
        'en': 'Temperature', 'da': 'Temperatur', 'de': 'Temperatur',
        'es': 'Temperatura', 'fr': 'Température', 'it': 'Temperatura',
        'nl': 'Temperatuur', 'no': 'Temperatur', 'pl': 'Temperatura',
        'sv': 'Temperatur',
    },
    'Today Energy Export': {
        'en': 'Today Energy Export', 'da': 'Dagens Eksport', 'de': 'Heutige Einspeisung',
        'es': 'Exportación Hoy', 'fr': "Export Aujourd'hui", 'it': 'Esportazione Oggi',
        'nl': 'Teruglevering Vandaag', 'no': 'Dagens Eksport', 'pl': 'Eksport Dzisiaj',
        'sv': 'Dagens Export',
    },
    'Today Energy Import': {
        'en': 'Today Energy Import', 'da': 'Dagens Import', 'de': 'Heutiger Netzbezug',
        'es': 'Importación Hoy', 'fr': "Import Aujourd'hui", 'it': 'Importazione Oggi',
        'nl': 'Afname Vandaag', 'no': 'Dagens Import', 'pl': 'Import Dzisiaj',
        'sv': 'Dagens Import',
    },
    'Today Load Consumption': {
        'en': 'Today Load Consumption', 'da': 'Dagens Forbrug', 'de': 'Heutiger Lastverbrauch',
        'es': 'Consumo de Carga Hoy', 'fr': 'Consommation Charge Aujourd\u2019hui', 'it': 'Consumo Carico Oggi',
        'nl': 'Belastingsverbruik Vandaag', 'no': 'Dagens Belastningsforbruk', 'pl': 'Zużycie Obciążenia Dzisiaj',
        'sv': 'Dagens Lastförbrukning',
    },
    'Total Load Consumption': {
        'en': 'Total Load Consumption', 'da': 'Samlet Forbrug', 'de': 'Gesamter Lastverbrauch',
        'es': 'Consumo Total de Carga', 'fr': 'Consommation Totale Charge', 'it': 'Consumo Totale Carico',
        'nl': 'Totaal Belastingsverbruik', 'no': 'Total Belastningsforbruk', 'pl': 'Całkowite Zużycie Obciążenia',
        'sv': 'Total Lastförbrukning',
    },
    'Total Production': {
        'en': 'Total Production', 'da': 'Samlet Produktion', 'de': 'Gesamtproduktion',
        'es': 'Producción Total', 'fr': 'Production Totale', 'it': 'Produzione Totale',
        'nl': 'Totale Productie', 'no': 'Total Produksjon', 'pl': 'Całkowita Produkcja',
        'sv': 'Total Produktion',
    },
}


def capability_title(english_title: str) -> dict[str, str]:
    """
    Returns the full translation object for a given English title.
    Falls back to {'en': english_title} if no translation entry exists,
    so an untranslated title never breaks capability generation.
    """
    return dict(_CAPABILITY_TITLES.get(english_title, {'en': english_title}))


# ── Name-based pattern rules ──────────────────────────────────────────────────
# Ordered by specificity. First match wins.
# (regex_pattern, homey_capability_id, english_title)
_NAME_RULES: list[tuple[str, str, str]] = [
    # PV channel power
    (r'\bpv1\b.+power|power.+\bpv1\b',        'measure_power.pv1',     'PV1 Power'),
    (r'\bpv2\b.+power|power.+\bpv2\b',        'measure_power.pv2',     'PV2 Power'),
    (r'\bpv3\b.+power|power.+\bpv3\b',        'measure_power.pv3',     'PV3 Power'),
    (r'\bpv4\b.+power|power.+\bpv4\b',        'measure_power.pv4',     'PV4 Power'),
    # Other power variants
    (r'battery.+power|power.+battery',         'measure_power.battery', 'Power Delivery'),
    (r'\bload\b.+power|power.+\bload\b',       'measure_power.load',    'Load Power'),
    (r'grid.+power|power.+grid',               'measure_power.grid',    'Grid Power'),
    (r'micro.+power|power.+micro',             'measure_power.micro',   'Micro-inverter Power'),
    # DC input power from PV array (before inverter conversion)
    (r'\binput.+power|pv.+power(?!.+\bpv\d)',  'measure_power.solar',   'Solar Power (DC Input)'),
    # Apparent and reactive power — must come before the generic AC output rule
    (r'apparent.+power|power.+apparent',       'measure_power.apparent', 'Output Apparent Power'),
    (r'reactive.+power|power.+reactive',       'measure_power.reactive', 'Output Reactive Power'),
    # Frequency — must come before AC output power to catch "AC Output Frequency"
    (r'ac.+freq|output.+freq|freq.+ac',        'measure_frequency',     'Grid Frequency'),
    # Main AC output (must come after the specific ones above)
    # Use \bac\b to avoid matching "active" (which starts with "ac")
    (r'ac.+output|total.+ac|output.+power|\bac\b.+power|inverter.+power',
                                               'measure_power',         'AC Output Power'),

    # PV voltage
    (r'\bpv1\b.+volt|volt.+\bpv1\b',          'measure_voltage.pv1',   'PV1 Voltage'),
    (r'\bpv2\b.+volt|volt.+\bpv2\b',          'measure_voltage.pv2',   'PV2 Voltage'),
    (r'\bpv3\b.+volt|volt.+\bpv3\b',          'measure_voltage.pv3',   'PV3 Voltage'),
    (r'\bpv4\b.+volt|volt.+\bpv4\b',          'measure_voltage.pv4',   'PV4 Voltage'),
    # Other voltage
    (r'battery.+volt|volt.+battery',           'measure_voltage.battery','Battery Voltage'),
    (r'\bl1\b.+volt|volt.+\bl1\b|phase.+a.+volt|volt.+phase.+a',
                                               'measure_voltage.l1',    'L1 Voltage'),
    (r'\bl2\b.+volt|volt.+\bl2\b|phase.+b.+volt|volt.+phase.+b',
                                               'measure_voltage.l2',    'L2 Voltage'),
    (r'\bl3\b.+volt|volt.+\bl3\b|phase.+c.+volt|volt.+phase.+c',
                                               'measure_voltage.l3',    'L3 Voltage'),
    (r'grid.+volt|volt.+grid|ac.+volt|grid.+\bl\b',
                                               'measure_voltage.grid',  'Grid Voltage'),

    # PV current
    (r'\bpv1\b.+curr|curr.+\bpv1\b',          'measure_current.pv1',   'PV1 Current'),
    (r'\bpv2\b.+curr|curr.+\bpv2\b',          'measure_current.pv2',   'PV2 Current'),
    (r'\bpv3\b.+curr|curr.+\bpv3\b',          'measure_current.pv3',   'PV3 Current'),
    (r'\bpv4\b.+curr|curr.+\bpv4\b',          'measure_current.pv4',   'PV4 Current'),
    # Other current
    (r'battery.+curr|curr.+battery',           'measure_current.battery','Battery Current'),
    (r'\bl1\b.+curr|curr.+\bl1\b',            'measure_current.l1',    'L1 Current'),
    (r'\bl2\b.+curr|curr.+\bl2\b',            'measure_current.l2',    'L2 Current'),
    (r'\bl3\b.+curr|curr.+\bl3\b',            'measure_current.l3',    'L3 Current'),
    (r'grid.+curr|curr.+grid|ac.+curr',        'measure_current.grid',  'Grid Current'),

    # Energy meters (order matters: specific before generic)
    # Daily import / export / load — must come before the generic daily/today production rule
    (r'(?:today|daily).+(?:import|bought)',     'meter_power.today_import',    'Today Energy Import'),
    (r'(?:today|daily).+(?:export|sold)',       'meter_power.today_export',    'Today Energy Export'),
    (r'(?:today|daily).+load',                 'meter_power.today_load',      'Today Load Consumption'),
    # Total load energy — must come before the generic "total production" rule
    (r'total.+load',                           'meter_power.load_total',      'Total Load Consumption'),
    # daily/today only for solar production — exclude grid/battery/load/import/export daily values
    (r'(?:daily|today)(?!.*export|.*import|.*buy|.*bought|.*sell|.*sold|.*battery|.*grid|.*load)',
                                               'meter_power.today',           'Daily Production'),
    # Total production — exclude rows that mention grid buy/sell/import/export
    (r'total.+prod|lifetime|total.+energy(?!.+(?:buy|bought|sell|sold|import|export))',
                                               'meter_power',                 'Total Production'),
    # Grid import: must begin with "total" or "grid" so daily variants ("Today Energy Import",
    # "Daily Energy Bought") do NOT match — they fall through to the rules above.
    (r'(?:total|grid).+(?:buy|bought|import)',  'meter_power.grid_import',     'Grid Import Energy'),
    # Grid export: same constraint.
    (r'(?:total|grid).+(?:sell|sold|export)',   'meter_power.grid_export',     'Grid Export Energy'),
    # "total.+charg" would also match "discharge" (contains "charg") — exclude via negative lookbehind.
    (r'battery.+charg.+energy|energy.+battery.+charg|total.+(?<!dis)charg',
                                               'meter_power.battery_charged', 'Battery Charged Energy'),
    (r'battery.+discharg.+energy|energy.+battery.+discharg|total.+discharg',
                                               'meter_power.battery_discharged', 'Battery Discharged Energy'),

    # Temperature — most-specific first
    (r'battery.+temp|temp.+battery',           'measure_temperature.battery',  'Battery Temperature'),
    # Radiator / AC heatsink temperature (secondary sensor, distinct from DC/module temp)
    (r'radiator.+temp|temp.+radiator|ac\s+temp|temp.+\bac\b',
                                               'measure_temperature.radiator', 'Radiator Temperature'),
    (r'temp',                                  'measure_temperature',          'Temperature'),

    # Frequency
    (r'freq',                                  'measure_frequency',     'Grid Frequency'),

    # Battery charging state (lookup: Charge / Stand-by / Discharge)
    (r'battery.+status|status.+battery|battery.+state|state.+battery',
                                               'battery_charging_state', 'Battery Status'),

    # Battery SOC
    (r'soc|state.of.charge|battery.+level',   'measure_battery',       'Battery SOC'),
]

# Homey built-in capability types that need `usingInsights: false` for sub-caps.
# Daily meters reset at midnight — their Insights graph would show a sawtooth, not useful.
_METER_SUBCAPS = {
    'meter_power.today',
    'meter_power.today_import',
    'meter_power.today_export',
    'meter_power.today_load',
    'meter_power.grid_import',
    'meter_power.grid_export',
    'meter_power.battery_charged',
    'meter_power.battery_discharged',
}


def _is_alarm_sensor(sensor: dict) -> bool:
    """Returns True if sensor represents a fault/alarm status via lookup."""
    if 'lookup' not in sensor:
        return False
    values = [str(o.get('value', '')).lower() for o in sensor.get('lookup', [])]
    return any(v in ('fault', 'alarm', 'warning') for v in values)


def _match_capability(sensor: dict) -> tuple[str, str] | None:
    """
    Returns (capability_id, title) for the sensor, or None if not mappable.
    Alarm sensors are detected first, then name-pattern rules are applied.
    """
    # Alarm via lookup table
    if _is_alarm_sensor(sensor):
        return ('alarm_generic', 'Fault / Alarm')

    name_lower = sensor.get('name', '').lower()

    for pattern, cap_id, title in _NAME_RULES:
        if re.search(pattern, name_lower):
            return (cap_id, title)

    # Fallback: class only
    cls = sensor.get('class', '')
    name = sensor.get('name', '')
    if cls == 'temperature':
        return ('measure_temperature', name)
    if cls == 'frequency':
        return ('measure_frequency', name)

    return None


def build_capabilities(sensors: list) -> tuple[list, dict]:
    """
    Given sensor definitions from a YAML 'parameters' list, returns:
    - capabilities:        list[str]  — Homey capability IDs
    - capabilitiesOptions: dict       — {cap_id: {title, usingInsights?}}

    Only the first sensor mapped to each capability ID is used (deduplication).
    """
    seen: set[str] = set()
    capabilities: list[str] = []
    options: dict = {}

    for sensor in sensors:
        match = _match_capability(sensor)
        if not match:
            continue
        cap_id, title = match
        if cap_id in seen:
            continue
        seen.add(cap_id)
        capabilities.append(cap_id)
        opt: dict = {'title': capability_title(title)}
        if cap_id in _METER_SUBCAPS:
            opt['usingInsights'] = False
        options[cap_id] = opt

    return capabilities, options


# Capabilities that belong to the battery device (not the inverter).
# Used at pairing to split sensors into two devices.
BATTERY_CAPS: frozenset[str] = frozenset({
    "measure_battery",
    "measure_power.battery",
    "measure_voltage.battery",
    "measure_current.battery",
    "measure_temperature.battery",
    "battery_charging_state",
    "meter_power.battery_charged",
    "meter_power.battery_discharged",
})


# Capabilities that belong to the grid meter device.
# At pairing these are remapped to standard Homey energy cap names.
GRID_METER_CAPS: frozenset[str] = frozenset({
    "meter_power.grid_import",
    "meter_power.grid_export",
    "measure_power.grid",
})

# Remap from internal cap IDs to the names expected by Homey Energy for a cumulative sensor.
GRID_CAP_REMAP: dict[str, str] = {
    "meter_power.grid_import": "meter_power",
    "meter_power.grid_export": "meter_power.exported",
    # measure_power.grid stays as-is on the grid meter device
}


# ── Toggleable detail capabilities (inverter device only) ─────────────────────
# Not added at pairing by default. Shown/hidden after pairing via a device
# setting (addCapability/removeCapability at runtime) — no re-pairing needed.
# Voltage/Current per PV string: diagnostic detail, redundant with PV{n} Power.
PV_DETAIL_CAPS: frozenset[str] = frozenset({
    "measure_voltage.pv1", "measure_current.pv1",
    "measure_voltage.pv2", "measure_current.pv2",
    "measure_voltage.pv3", "measure_current.pv3",
    "measure_voltage.pv4", "measure_current.pv4",
})

# L1 Voltage/Current: the inverter's own AC/grid connection point reading —
# NOT the same as GRID_METER_CAPS (which requires a CT and feeds the grid
# meter device). Diagnostic detail, redundant with AC Output Power.
AC_DETAIL_CAPS: frozenset[str] = frozenset({
    "measure_voltage.l1", "measure_current.l1",
})

# addCapability() at runtime does NOT inherit the per-device title from
# pairing's capabilitiesOptions — it falls back to the capability's generic
# built-in title (e.g. every measure_voltage.* tile just shows "Voltage").
# _sync_detail_caps() in device.py uses this to call setCapabilityOptions()
# right after adding, restoring the same title build_capabilities() would
# have set at pairing time.
DETAIL_CAP_TITLES: dict[str, str] = {
    "measure_voltage.pv1": "PV1 Voltage", "measure_current.pv1": "PV1 Current",
    "measure_voltage.pv2": "PV2 Voltage", "measure_current.pv2": "PV2 Current",
    "measure_voltage.pv3": "PV3 Voltage", "measure_current.pv3": "PV3 Current",
    "measure_voltage.pv4": "PV4 Voltage", "measure_current.pv4": "PV4 Current",
    "measure_voltage.l1": "L1 Voltage", "measure_current.l1": "L1 Current",
}


def get_sensor_capability_map(sensors: list) -> dict[str, str]:
    """
    Returns {sensor_name: homey_capability_id} for use during polling.
    Used to map parsed register values to Homey capability updates.
    First match per capability wins (deduplication).
    """
    result: dict[str, str] = {}
    seen: set[str] = set()

    for sensor in sensors:
        match = _match_capability(sensor)
        if not match:
            continue
        cap_id, _ = match
        if cap_id not in seen:
            seen.add(cap_id)
            result[sensor['name']] = cap_id

    return result
