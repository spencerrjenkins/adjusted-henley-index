"""Central configuration: paths, the indicator registry, the friction ladder,
the pillar structure, and the lens (weight-vector) definitions.

Everything that encodes an analyst judgement call lives in this one module, so
that the set of things a reader has to argue with is finite and enumerable.
That is the first recommendation of the OECD/JRC *Handbook on Constructing
Composite Indicators* (2008): make the framework explicit before you make it
quantitative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
MANUAL = DATA / "manual"
PROCESSED = DATA / "processed"
OUTPUT = ROOT / "output"
FIGURES = OUTPUT / "figures"
TABLES = OUTPUT / "tables"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"

for _p in (RAW, MANUAL, PROCESSED, OUTPUT, FIGURES, TABLES, DOCS):
    _p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# The friction ladder
# ---------------------------------------------------------------------------
# Henley scores entry rights as a binary: 1 if you can board a plane without
# having asked a government for permission first, 0 otherwise. That is a clean,
# defensible line -- and it is also the single largest information loss in the
# index, because it puts "walk through the e-gate at Schiphol" and "fill in a
# 40-question eTA form and pay GBP 16" in the same bucket, while putting "eTA"
# and "e-Visa" (a form, a fee, and a wait, but no consulate visit) in different
# ones.
#
# GRADED assigns partial credit along that continuum. The numbers are ordinal
# judgements, not measurements, so every result computed with them is also
# reported under BINARY_HENLEY (Henley's own rule) and STRICT (only true
# visa-free counts) -- see `analysis/sensitivity.py`. If a finding only holds
# under one ladder, it is a finding about the ladder, not about passports.
ACCESS_LADDERS: dict[str, dict[str, float]] = {
    # Henley & Partners' published rule, reproduced exactly.
    "binary_henley": {
        "visa_free": 1.0,
        "visa_on_arrival": 1.0,
        "eta": 1.0,
        "e_visa": 0.0,
        "visa_required": 0.0,
        "no_admission": 0.0,
    },
    # Default. Partial credit for pre-departure paperwork that is granted
    # near-automatically (eTA, e-Visa) but is still a permission request.
    "graded": {
        "visa_free": 1.00,
        "visa_on_arrival": 0.85,   # no pre-departure step, but a queue and a fee
        "eta": 0.70,               # online, minutes, near-automatic approval
        "e_visa": 0.35,            # online, days of lead time, refusable
        "visa_required": 0.00,     # consulate appointment, biometrics, interview
        "no_admission": 0.00,      # entry refused outright
    },
    # The purist reading: only entry with no authorisation of any kind.
    "strict": {
        "visa_free": 1.0,
        "visa_on_arrival": 0.0,
        "eta": 0.0,
        "e_visa": 0.0,
        "visa_required": 0.0,
        "no_admission": 0.0,
    },
}
DEFAULT_LADDER = "graded"

# Typical permitted stay, in days, for rows where the source matrix records a
# category rather than an explicit day count. Used only by the duration-weighted
# variant; sourced from the modal published allowance for each category.
DEFAULT_STAY_DAYS: dict[str, int] = {
    "visa_free": 90,
    "visa_on_arrival": 30,
    "eta": 90,
    "e_visa": 30,
    "visa_required": 0,
    "no_admission": 0,
}
STAY_DAYS_CAP = 180  # a half-year of permitted presence saturates the benefit


# ---------------------------------------------------------------------------
# Indicator registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Indicator:
    """One measured attribute of a destination country.

    direction: +1 if more is better for a traveller, -1 if less is better.
    transform: 'log' for indicators spanning orders of magnitude (all the
               count- and money-denominated ones), 'linear' for bounded scores
               and rates.
    """

    key: str
    pillar: str
    source: str          # worldbank | owid | undp | restcountries
    code: str
    label: str
    unit: str
    direction: int = 1
    transform: str = "linear"
    note: str = ""


INDICATORS: tuple[Indicator, ...] = (
    # -- Pillar: economy -- can you earn, trade, and transact there? ---------
    Indicator("gdp_pc_ppp", "economy", "worldbank", "NY.GDP.PCAP.PP.CD",
              "GDP per capita, PPP", "int'l $", 1, "log",
              "Individual-level prosperity: wages, prices, standard of living."),
    Indicator("gdp_total_ppp", "economy", "worldbank", "NY.GDP.MKTP.PP.CD",
              "GDP, PPP", "int'l $", 1, "log",
              "Market size: how much economic activity the door opens onto."),
    Indicator("trade_openness", "economy", "worldbank", "NE.TRD.GNFS.ZS",
              "Trade", "% of GDP", 1, "linear",
              "How externally engaged the economy is; proxies ease of doing "
              "business as a foreigner."),

    # -- Pillar: development -- is it a functioning, modern place? -----------
    Indicator("hdi", "development", "undp", "hdi",
              "Human Development Index", "0-1", 1, "linear",
              "UNDP composite of life expectancy, education, and income."),
    Indicator("internet_users", "development", "worldbank", "IT.NET.USER.ZS",
              "Individuals using the internet", "% of pop.", 1, "linear",
              "Digital infrastructure; the binding constraint for remote work."),
    Indicator("tertiary_enroll", "development", "worldbank", "SE.TER.ENRR",
              "Tertiary school enrolment", "% gross", 1, "linear",
              "Higher-education capacity; proxies value as a study destination."),

    # -- Pillar: scale -- how much world is behind the door? -----------------
    Indicator("population", "scale", "worldbank", "SP.POP.TOTL",
              "Population", "people", 1, "log",
              "Demographic reach, independent of wealth."),
    Indicator("surface_area", "scale", "worldbank", "AG.SRF.TOTL.K2",
              "Surface area", "sq. km", 1, "log",
              "Physical extent: how much there is to actually go and see."),

    # -- Pillar: draw -- do people want to go, and can they get there? -------
    Indicator("tourist_arrivals", "draw", "worldbank", "ST.INT.ARVL",
              "International tourist arrivals", "people/yr", 1, "log",
              "Revealed preference: where the world actually chooses to go."),
    Indicator("tourism_receipts", "draw", "worldbank", "ST.INT.RCPT.CD",
              "International tourism receipts", "US$/yr", 1, "log",
              "Value, not just volume, of the tourism draw."),
    Indicator("air_departures", "draw", "worldbank", "IS.AIR.DPRT",
              "Registered carrier departures", "flights/yr", 1, "log",
              "Air connectivity. A visa waiver you cannot fly to is theoretical."),

    # -- Pillar: security -- is the access safely usable? --------------------
    Indicator("rule_of_law", "security", "owid", "rule_of_law_vdem__estimate_best",
              "Rule of law index (V-Dem)", "0-1", 1, "linear",
              "Are laws applied predictably and impartially to a foreigner?"),
    Indicator("electoral_democracy", "security", "owid", "electdem_vdem__estimate_best",
              "Electoral democracy index (V-Dem)", "0-1", 1, "linear",
              "Civil-liberties environment a visitor is subject to."),
    Indicator("homicide_rate", "security", "worldbank", "VC.IHR.PSRC.P5",
              "Intentional homicides", "per 100k", -1, "log",
              "Physical safety. Log-scaled: the gap from 1 to 10 per 100k "
              "matters more than 40 to 50."),

    # -- Pillar: cost -- how far does your money go? -------------------------
    # The World Bank retired its published price-level series (PA.NUS.PPPC.RF),
    # so this is rebuilt from its definition: nominal GDP in US dollars divided
    # by GDP in PPP international dollars is exactly the ratio of the PPP
    # conversion factor to the market exchange rate. Below 1 means a
    # hard-currency visitor's money stretches further than at home.
    Indicator("price_level", "cost", "derived", "NY.GDP.MKTP.CD / NY.GDP.MKTP.PP.CD",
              "Price level (PPP-to-market exchange-rate ratio)", "ratio", -1, "linear",
              "Cost of being there, relative to the world average."),
)

# Series fetched because something else is derived from them, not scored directly.
SUPPORT_SERIES: dict[str, str] = {
    "gdp_total_usd": "NY.GDP.MKTP.CD",
}

# World Bank keeps publishing a country's last observation forever, so a naive
# "latest non-null" pull happily returns a 1994 tertiary-enrolment figure next
# to a 2025 GDP figure. Anything older than this is treated as missing and
# imputed like any other gap, with the substitution recorded in the provenance
# table. The exception is tourism, where the entire world's latest data is
# pre-pandemic and dropping it would delete the pillar.
VINTAGE_FLOOR = 2012
VINTAGE_FLOOR_EXEMPT = {"tourist_arrivals", "tourism_receipts"}

INDICATOR_BY_KEY = {ind.key: ind for ind in INDICATORS}
PILLARS: tuple[str, ...] = ("economy", "development", "scale", "draw", "security", "cost")
PILLAR_LABELS = {
    "economy": "Economy",
    "development": "Development",
    "scale": "Scale",
    "draw": "Draw",
    "security": "Security",
    "cost": "Affordability",
}
PILLAR_BLURBS = {
    "economy": "Can you earn, trade and transact there?",
    "development": "Is it a functioning, connected, modern place?",
    "scale": "How much world sits behind the door?",
    "draw": "Do people want to go — and can flights get you there?",
    "security": "Is the access safely and predictably usable?",
    "cost": "How far does a visitor's money go?",
}


# ---------------------------------------------------------------------------
# Lenses: pillar weight vectors
# ---------------------------------------------------------------------------
# A weight vector is a statement about *whose* mobility you are measuring. There
# is no view from nowhere: Henley's flat count is itself a weight vector (every
# destination = 1), it just never says so. Rather than pick one and call it the
# truth, the project computes several and reports where they agree.
@dataclass(frozen=True)
class Lens:
    key: str
    label: str
    question: str
    weights: dict[str, float]


LENSES: tuple[Lens, ...] = (
    Lens("balanced", "Balanced",
         "How much of the world's opportunity, on every axis at once, can you reach?",
         {"economy": 0.25, "development": 0.20, "scale": 0.15,
          "draw": 0.15, "security": 0.20, "cost": 0.05}),
    Lens("business", "Business",
         "How much economic activity can you show up to a meeting in?",
         {"economy": 0.40, "development": 0.15, "scale": 0.20,
          "draw": 0.05, "security": 0.20, "cost": 0.00}),
    Lens("leisure", "Leisure",
         "How much of the world worth visiting can you actually go and see?",
         {"economy": 0.05, "development": 0.10, "scale": 0.10,
          "draw": 0.40, "security": 0.20, "cost": 0.15}),
    Lens("settlement", "Settlement",
         "How much of the world could you plausibly live and work in?",
         {"economy": 0.20, "development": 0.35, "scale": 0.05,
          "draw": 0.00, "security": 0.35, "cost": 0.05}),
    Lens("reach", "Raw reach",
         "How many people and how much output sit behind the doors you can open?",
         {"economy": 0.50, "development": 0.00, "scale": 0.50,
          "draw": 0.00, "security": 0.00, "cost": 0.00}),
)
LENS_BY_KEY = {lens.key: lens for lens in LENSES}
HEADLINE_LENS = "balanced"


# ---------------------------------------------------------------------------
# Blocs, for the regional / political-club analysis
# ---------------------------------------------------------------------------
BLOCS: dict[str, list[str]] = {
    "EU-27": ["AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA",
              "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD",
              "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"],
    "GCC": ["ARE", "BHR", "KWT", "OMN", "QAT", "SAU"],
    "ASEAN": ["BRN", "KHM", "IDN", "LAO", "MYS", "MMR", "PHL", "SGP", "THA", "VNM"],
    "African Union": ["DZA", "AGO", "BEN", "BWA", "BFA", "BDI", "CMR", "CPV", "CAF",
                      "TCD", "COM", "COG", "COD", "CIV", "DJI", "EGY", "GNQ", "ERI",
                      "SWZ", "ETH", "GAB", "GMB", "GHA", "GIN", "GNB", "KEN", "LSO",
                      "LBR", "LBY", "MDG", "MWI", "MLI", "MRT", "MUS", "MAR", "MOZ",
                      "NAM", "NER", "NGA", "RWA", "STP", "SEN", "SYC", "SLE", "SOM",
                      "ZAF", "SSD", "SDN", "TZA", "TGO", "TUN", "UGA", "ZMB", "ZWE"],
    "Mercosur": ["ARG", "BRA", "PRY", "URY", "BOL"],
    "Five Eyes": ["AUS", "CAN", "NZL", "GBR", "USA"],
    "CIS": ["ARM", "AZE", "BLR", "KAZ", "KGZ", "MDA", "RUS", "TJK", "UZB"],
    "Caribbean CBI": ["ATG", "DMA", "GRD", "KNA", "LCA", "VUT"],
}

# Countries that sell citizenship outright, for the citizenship-by-investment
# discussion. VUT is Pacific, not Caribbean, but belongs to the same market.
CBI_COUNTRIES = ["ATG", "DMA", "GRD", "KNA", "LCA", "VUT", "MLT", "TUR", "EGY", "JOR", "NRU"]

# Normalisation is winsorised before min-max scaling so that one extreme
# destination (Monaco's GDP per capita, Tuvalu's population) cannot compress the
# other 197 into the bottom of the range.
WINSOR_LIMITS = (0.01, 0.99)

RANDOM_SEED = 20260728
