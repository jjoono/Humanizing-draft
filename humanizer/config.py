"""Corpus selection settings (RULES.md section 1). Edit here to retarget the corpus."""
from __future__ import annotations

import re

YEAR_MAX = 2019  # rule C1: published before 2020
YEAR_MIN = 1987  # Tang & VanSlyke's OLED paper; nothing older is relevant

# rule C2: one OpenAlex title/abstract search per entry, results are merged.
DOMAIN_QUERIES: dict[str, list[str]] = {
    "oled": [
        '"organic light-emitting diode"', '"organic light-emitting device"', "OLED",
        '"thermally activated delayed fluorescence"', '"phosphorescent organic light-emitting"',
        '"organic electroluminescent"', '"light outcoupling" organic',
    ],
    "peled": [
        '"perovskite light-emitting"', '"perovskite LED"', '"perovskite electroluminescence"',
        '"perovskite nanocrystal" light-emitting',
    ],
    "qled": [
        '"quantum dot light-emitting"', "QLED", '"quantum-dot LED"', '"colloidal quantum dot" electroluminescence',
    ],
    "optics_display": [
        '"liquid crystal display"', '"micro-LED" display', '"microcavity" light-emitting', '"light extraction efficiency"',
        '"color conversion" display', '"photonic crystal" light-emitting', '"flexible display"',
    ],
}

# Topic words used for the small "topic match" component of the priority score.
TOPIC_TERMS = [
    "oled", "light-emitting", "electroluminescen", "perovskite", "quantum dot", "display", "outcoupling",
    "microcavity", "exciton", "phosphorescen", "delayed fluorescence", "external quantum efficiency", "emitter",
    "liquid crystal", "light extraction", "micro-led",
]

REVIEW_TITLE = re.compile(r"\b(review|reviews|progress report|anniversary article|perspective|overview|"
                          r"tutorial|roadmap|state of the art|recent advances|recent progress)\b", re.I)
REVIEW_VENUE = re.compile(r"(chemical reviews|reviews of modern physics|chemical society reviews|"
                          r"progress in|annual review|reports on progress|materials science and engineering: r)", re.I)

# rule C3: US + EU/EEA + UK + Switzerland.
PRIORITY_COUNTRIES = {
    "US",
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
    "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    "GB", "CH", "NO", "IS",
}

# Flagship venues in the field (case-insensitive substring match on the source name).
PRIORITY_VENUES = [
    "nature", "science", "advanced materials", "advanced functional materials", "advanced optical materials",
    "applied physics letters", "journal of applied physics", "physical review", "optics express", "optica",
    "organic electronics", "acs nano", "nano letters", "journal of the american chemical society",
    "light: science", "journal of the society for information display", "chemistry of materials",
    "acs photonics", "laser & photonics reviews", "journal of materials chemistry",
]

PRIORITY_WEIGHTS = {"citations": 0.40, "age": 0.20, "affiliation": 0.25, "venue": 0.10, "topic": 0.05}
LAST_AUTHOR_BONUS = 0.2  # added to the affiliation component when the last author is US/EU
AGE_SPAN = 20  # years; 2019 scores 0 and anything older than YEAR_MAX - AGE_SPAN scores 1
