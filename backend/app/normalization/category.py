"""Deterministic transaction categorization.

No external AI/LLM calls. Rules match against the normalized merchant
name, the raw description, or both ("any"), optionally only for money in
or money out, with priority ordering so user-defined rules always win
over built-in defaults. Built-in rules are synchronized with
DEFAULT_CATEGORY_RULES on every import (see sync_default_category_rules).
"""
from __future__ import annotations

import re

from sqlmodel import Session, select

from app.db.models import CategoryRule

# (pattern, category, amount_sign, priority). Word boundaries (\b) keep
# e.g. "rent" out of "Rentenversicherung"/"Parent" and "esso" out of
# "Espresso". More specific rules get a lower (= earlier) priority.
DEFAULT_CATEGORY_RULES: list[tuple[str, str, str, int]] = [
    (r"\bnetflix\b|\bspotify\b|\bdisney\+?|\bprime video\b|\bamazon prime\b|\byoutube premium\b|\bdazn\b|\baudible\b|"
     r"apple\.com/bill|\bgoogle play\b|\bdeezer\b|\bsky deutschland\b|\bpatreon\b|\bchatgpt\b|\bopenai\b",
     "Subscriptions", "negative", 50),
    (r"\bsalary\b|\bgehalt\b|\blohn\b|\bpayroll\b|\bbezuege\b|\bbezüge\b|\bbesoldung\b|arbeitsentgelt",
     "Salary", "positive", 50),
    (r"\bfinanzamt\b|steuer\b|\bsteuern\b|\btax(es)?\b", "Taxes", "negative", 60),
    (r"versicherung|vers\.\s?verein|\binsurance\b|krankenkasse|\baok\b|\bbarmer\b|\bdak\b|\bhuk\b|\bergo\b|\ballianz\b|\baxa\b|"
     r"\bdebeka\b|\bdevk\b", "Insurance", "negative", 70),
    (r"\bmiete\b|mietzahlung|\brent\b|\bhausgeld\b|\bmortgage\b|\bnebenkosten\b|hausverwaltung",
     "Housing", "negative", 80),
    (r"stromrechnung|\bstrom\b|stadtwerke|\belectricity\b|gas bill|\butilit(y|ies)\b|wasserwerk|\bvattenfall\b|"
     r"\be\.?on\b|\benbw\b|\byello\b|\bgasag\b|rundfunk|beitragsservice|\btelekom\b|\bvodafone\b|\bo2\b|"
     r"telef[oó]nica|\b1&1\b|\bcongstar\b|mobilfunk|\binternet\b|glasfaser",
     "Utilities", "negative", 90),
    (r"\blidl\b|\baldi\b|\brewe\b|\bedeka\b|\bkaufland\b|\bnetto\b|\bpenny\b|\bnorma\b|\btegut\b|\bglobus\b|"
     r"\balnatura\b|\bdenns\b|\bnahkauf\b|\bmarktkauf\b|\bfamila\b|supermarkt|supermarket|\bgrocery\b",
     "Groceries", "any", 100),
    (r"\brestaurant\b|\bmcdonald'?s?\b|\bburger king\b|\bkfc\b|\bsubway\b|\bpizz|\bcaf[eé]\b|\bstarbucks\b|"
     r"\blieferando\b|\bwolt\b|\buber eats\b|\bdomino'?s\b|\bvapiano\b|b(ä|ae)ckerei|\bbackwerk\b|\bmensa\b|"
     r"\bimbiss\b|d(ö|oe)ner",
     "Food", "any", 100),
    (r"\buber\b|\blyft\b|\btaxi\b|deutsche bahn|\bdb (bahn|fernverkehr|regio|vertrieb)\b|\bbvg\b|\bmvg\b|\bhvv\b|"
     r"\bvbb\b|\brmv\b|\bkvb\b|\bflixbus\b|\bflixtrain\b|deutschlandticket|\bfree now\b|parkhaus|parkgeb(ü|ue)hr|"
     r"\beasypark\b|\bparkster\b",
     "Transport", "any", 100),
    (r"\bshell\b|\baral\b|\besso\b|tankstelle|\bpetrol\b|\bfuel\b|\bjet tankstelle\b|totalenergies|\bavia\b|\bagip\b",
     "Transport", "any", 100),
    (r"\bamazon\b|\bamzn\b|\bamz\*|\bzalando\b|\bikea\b|\bmedia ?markt\b|\bsaturn\b|\botto\b|\bebay\b|\bh&m\b|\bzara\b|"
     r"\bprimark\b|\bdecathlon\b|\babout you\b|\bobi\b|\bbauhaus\b|\bhornbach\b|\btoom\b|\bthalia\b|\bhugendubel\b|"
     r"\bgaleria\b|\btk maxx\b|\bdouglas\b|dm-drogerie|\bdm drogerie\b|\brossmann\b|\btemu\b|\bshein\b|\baliexpress\b",
     "Shopping", "any", 100),
    (r"\bhotel\b|\bhostel\b|\bairbnb\b|booking\.com|\bexpedia\b|\bairline\b|\bryanair\b|\blufthansa\b|\beurowings\b|"
     r"\beasyjet\b|\bcondor\b|\btui\b",
     "Travel", "any", 100),
    (r"\bapotheke\b|\bpharmacy\b|\barzt\b|(ä|ae)rzt|\bdoctor\b|zahnarzt|\bdentist\b|\bhospital\b|krankenhaus|\bklinik|"
     r"\bphysio|\boptiker\b|\bfielmann\b|\bdocmorris\b",
     "Health", "any", 100),
    (r"\buniversit(y|aet|ät)\b|\bhochschule\b|studierendenwerk|studentenwerk|semesterbeitrag|\btuition\b|\budemy\b|"
     r"\bcoursera\b|school fee|volkshochschule",
     "Education", "any", 100),
    (r"\bcinema\b|\bkino\b|\bcinemaxx\b|\bcineplex\b|\bconcert\b|\bkonzert\b|\btheat(re|er)\b|\beventim\b|"
     r"\bticketmaster\b|\bsteam\b|\bplaystation\b|\bnintendo\b|\bxbox\b",
     "Entertainment", "any", 100),
    (r"geldautomat|\bbargeld|\bauszahlung\b|\batm\b|cash withdrawal", "Cash", "negative", 100),
    (r"kontof(ü|ue)hrung|\bentgelt\b|geb(ü|ue)hr|\bzinsen\b|auslandseinsatz", "Fees", "negative", 100),
    # Paying off a card from the bank account: a transfer ("Transfers") once
    # it is linked to the card's statement or payment line; until then — or
    # when the card's purchases aren't imported at all — an expense of its
    # own kind, recognizable as a card bill.
    # ("KAR TENABRECHNUNG": a bank's text broken over two lines)
    (r"\bamerican express\b|\bamex\b|kreditkarten?abrechnung|\bkar ?tenabrechnung|\bkreditkarte\b|\bvisa card\b"
     r"|\bmastercard\b",
     "Card bills", "negative", 40),
    (r"\bspende|\bdonation\b|\bunicef\b|\bwikimedia\b|\bgreenpeace\b|(ä|ae)rzte ohne grenzen|brot f(ü|ue)r die welt",
     "Donations", "negative", 100),
    # More well-known chains and services (brand names only — generic words
    # such as "shop", "markt" or "bar" would misfire, and "Müller" is as
    # often a surname as the drugstore).
    (r"\bbilla\b|\bspar\b|\bhofer kg\b|\bmigros\b|\bdenner\b|\bbio company\b|\bakzenta\b|\bwasgau\b|\bfeneberg\b|"
     r"\btrinkgut\b|getr(ä|ae)nke ?hoffmann|\bfristo\b|asia ?markt|\bmetzgerei\b|\bfleischerei\b|\bflink\b|"
     r"\bgorillas\b|\bknuspr\b|\bbiomarkt\b|\bhofladen\b",
     "Groceries", "any", 100),
    (r"\bburgerme\b|\bfive guys\b|l'?osteria|\bnordsee\b|dean ?& ?david|hans im gl(ü|ue)ck|\bblock house\b|"
     r"\bpeter pane\b|\bsushi\b|\bramen\b|\bkeba[bp]\b|\bbistro\b|gastst(ä|ae)tte|\bbrauhaus\b|\bbiergarten\b|"
     r"\bkantine\b|\bcafeteria\b|eiscaf(e|é)|\bgelato\b|kamps b(ä|ae)ck|le crobag|back-?factory|"
     r"\bfoodora\b|\bdeliveroo\b|too good to go|\btrattoria\b|\bosteria\b|\btaverna\b|"
     r"\bwirtshaus\b|\bgasthof\b|\bgasthaus\b|\bfalafel\b",
     "Food", "any", 100),
    (r"\bnvv\b|\bvgf\b|\bvrr\b|\bvvs\b|\bmvv\b|\bnaldo\b|\bgvh\b|(ü|ue)stra\b|\brheinbahn\b|\bbolt\b|"
     r"\bshare now\b|\bstadtmobil\b|\bflinkster\b|\bnextbike\b|call a bike|\ba\.?t\.?u\b|\bpitstop\b|"
     r"\bcarglass\b|\bapcoa\b|\bcontipark\b|q-park|\bomv\b|\borlen\b|\bionity\b|\ballego\b|\bfastned\b|"
     r"supercharger|verkehrsbetriebe|verkehrsverbund|\bmetronom\b|\bvlexx\b|\babellio\b|\btransdev\b",
     "Transport", "any", 100),
    (r"\btrivago\b|\bholidaycheck\b|\bopodo\b|\bwizz ?air\b|\bklm\b|air france|british airways|\bsunexpress\b|"
     r"turkish airlines|\bemirates\b|\bmarriott\b|\bhilton\b|\bibis\b|motel one|b&b hotel|premier inn|"
     r"meininger hotel|jugendherberge|\bhostelworld\b|ferienwohnung",
     "Travel", "any", 100),
    (r"\bkik\b|\btakko\b|\bc ?& ?a\b|\bdeichmann\b|\bsnipes\b|foot locker|new yorker|s\.oliver|tom tailor|"
     r"\buniqlo\b|\bbershka\b|pull ?& ?bear|peek ?& ?cloppenburg|\bbreuninger\b|\bkarstadt\b|\bkaufhof\b|"
     r"\bwoolworth\b|\btedi\b|nanu-?nana|\bxxxlutz\b|h(ö|oe)ffner|\bjysk\b|bettenlager|m(ö|oe)max|"
     r"segm(ü|ue)ller|conrad electronic|\bcyberport\b|notebooksbilliger|\beuronics\b|\bgamestop\b|\bbudni|"
     r"\bsmyths\b|\bintersport\b|\bsportscheck\b|\bglobetrotter\b|jack wolfskin|\bbonprix\b|\btchibo\b|"
     r"\bfressnapf\b|\bzooplus\b|\bfutterhaus\b|dehner garten|blume 2000|\betsy\b|\bvinted\b|kleinanzeigen|"
     r"\brebuy\b|\bmomox\b|\bmedimops\b|buchhandlung|\bweltbild\b|\bosiander\b|\bmayersche\b|\bmcpaper\b|"
     r"\bhagebau\b|musikhaus thomann|thomann\.de|m(ü|ue)ller drogerie",
     "Shopping", "any", 100),
    (r"sanit(ä|ae)tshaus|h(ö|oe)rger(ä|ae)te|heilpraktiker|\bmedpex\b|shop-? ?apotheke|\baponeo\b|\bmycare\b|"
     r"apollo-? ?optik|krankengymnastik|ergotherapie|logop(ä|ae)die|physiotherapie|\bmcfit\b|\bfitx\b|clever fit|"
     r"john reed|urban sports|\bfitness",
     "Health", "any", 100),
    (r"\bcinestar\b|\bkinopolis\b|\bmuseum\b|\btierpark\b|freizeitpark|europa-?park|phantasialand|"
     r"schwimmbad|hallenbad|freibad|\btherme\b|\bbowling\b|\bminigolf\b|\blasertag\b|philharmonie",
     "Entertainment", "any", 100),
    (r"\bicloud\b|game pass|\badobe\b|\bdropbox\b|google one|\bgithub\b|\bduolingo\b|\bheadspace\b|"
     r"\btinder\b|\bparship\b|\brtl\+|\bjoyn\b|magenta ?tv|paramount\+|\bcrunchyroll\b|kindle unlimited|"
     r"\bnordvpn\b|\bexpressvpn\b|\b1password\b|\bmidjourney\b|\banthropic\b|claude\.ai|\bcanva\b|"
     r"\bgrammarly\b|apple music",
     "Subscriptions", "negative", 50),
    (r"\bnaturstrom\b|\blichtblick\b|\bpolarstern\b|\beprimo\b|\btibber\b|octopus energy|\bpyur\b|"
     r"\bunitymedia\b|\bnetcologne\b|\bm-net\b|\bdrillisch\b|\bsimyo\b|aldi talk|\bfraenk\b|\blebara\b|"
     r"\blyca ?mobile\b|blau\.de|\bnetzclub\b|abfallwirtschaft|m(ü|ue)llabfuhr",
     "Utilities", "negative", 90),
    (r"techniker krankenkasse|\bikk\b|\bbkk\b|hanse ?merkur|signal iduna|\br\+v\b|\bprovinzial\b|\blvm\b|"
     r"w(ü|ue)rttembergische|\bgothaer\b|\bgenerali\b|cosmos ?direkt|haftpflicht|hausrat",
     "Insurance", "negative", 70),
    (r"sprachschule|nachhilfe|fahrschule|\bkita\b|kindergarten|stadtbibliothek", "Education", "any", 100),
    (r"\bvonovia\b|deutsche wohnen|\bgewobag\b|wohnungsbau|wohnungsgenossenschaft|studentenwohnheim",
     "Housing", "negative", 80),
    # Card terminals cut merchant names short and drop spaces ("DBVERTRIEBG",
    # "DLH" for Lufthansa); generic words a merchant's name is made of.
    (r"\bdb ?vertrieb|\bdbvertrieb|\bdb ?fernverkehr|\bdb ?regio|\bbahn\.de\b|\bbahnhof\b|\bparkautomat|"
     r"\bparkhaus|\bparkplatz|wasch(?:park|anlage|stra(?:ss|ß)e|center|box)|\bcar ?wash|\bsixt\b|\beuropcar\b|"
     r"\bmietwagen|\bcarsharing|\bblablacar",
     "Transport", "any", 90),
    (r"\bdlh\b|\bflughafen|\bairport\b|\bairlines?\b|\bairways\b|\breiseb(?:ü|ue)ro|\bferienwohnung|\bjugendherberge",
     "Travel", "any", 90),
    (r"marc ?o'? ?polo|\besprit\b|jack ?& ?jones|\bnike\b|\badidas\b|\bpuma\b|\breebok\b|\basics\b|"
     r"\bnew balance\b|\bsalomon\b|\bthe north face\b|\bjack wolfskin\b|\bvaude\b|(?<![a-z])sports?(?:shop|store|haus)?\b|"
     r"(?<![a-z])runners?\b|\bschuhe?\b|\bschuhhaus|\bmode\b|\bmodehaus|\bboutique\b|\btextil|\bbekleidung|"
     r"\bmedimax\b|\bcyberport\b|\bnotebooksbilliger\b|\bfriseur|\bbarber",
     "Shopping", "any", 90),
    (r"\bapple\.com|\bitunes\b|\bgoogle \*|\bgoogle play|\bmicrosoft\b|\badobe\b|\bdropbox\b|\bchatgpt|\bopenai\b",
     "Subscriptions", "negative", 90),
    (r"\bgez\b|beitrags ?service", "Utilities", "negative", 90),
]

# Stored under these (English) names, shown translated (frontend
# lib/categories.ts keeps the same list).
BUILT_IN_CATEGORIES = (
    "Food", "Groceries", "Housing", "Transport", "Travel", "Shopping", "Subscriptions", "Entertainment", "Health",
    "Education", "Utilities", "Insurance", "Taxes", "Cash", "Fees", "Donations", "Salary", "Other Income",
    "Other Expense", "Transfers", "Card bills",
)

# What a booking nothing could sort ends up as.
UNSORTED_CATEGORIES = frozenset({"Other Expense", "Other Income"})
# Categories that say nothing about what was bought: unsorted, or money between own accounts.
NO_SIGNAL_CATEGORIES = UNSORTED_CATEGORIES | {"Transfers", "Card bills"}

# On a credit-card account, the built-in "card payment" rule would mislabel
# the card's own charges (e.g. an "AMEX" annual fee) as transfers.
CARD_ACCOUNT_EXCLUDED = frozenset({"Transfers", "Card bills"})


def sync_default_category_rules(session: Session) -> None:
    """Make the built-in rules in the database match DEFAULT_CATEGORY_RULES
    exactly. User-defined rules are left alone."""
    existing = session.exec(select(CategoryRule).where(CategoryRule.is_user_defined == False)).all()  # noqa: E712
    wanted = {pattern: (category, sign, priority) for pattern, category, sign, priority in DEFAULT_CATEGORY_RULES}
    kept = set()
    changed = False
    for rule in existing:
        if wanted.get(rule.pattern) == (rule.category, rule.amount_sign, rule.priority) \
                and rule.is_regex and rule.match_field == "any" and rule.pattern not in kept:
            kept.add(rule.pattern)
        else:
            session.delete(rule)
            changed = True
    for pattern, category, sign, priority in DEFAULT_CATEGORY_RULES:
        if pattern not in kept:
            session.add(CategoryRule(
                pattern=pattern, is_regex=True, match_field="any",
                category=category, priority=priority, amount_sign=sign,
            ))
            changed = True
    if changed:
        session.commit()



def _sign_matches(rule: CategoryRule, amount_minor: int) -> bool:
    sign = getattr(rule, "amount_sign", "any") or "any"
    if sign == "positive":
        return amount_minor > 0
    if sign == "negative":
        return amount_minor < 0
    return True


def categorize(
    merchant: str | None,
    description: str | None,
    amount_minor: int,
    rules: list[CategoryRule],
    is_income: bool | None = None,
    exclude: frozenset[str] = frozenset(),
    merchant_category: str | None = None,
) -> str | None:
    """Returns the category of the first matching rule, else the one the
    card network's `merchant_category` stands for, else a generic fallback.
    `is_income` overrides the sign-based fallback choice (e.g. a refund on
    a credit card is positive but not income)."""
    income = amount_minor > 0 if is_income is None else is_income
    default = "Other Income" if income else "Other Expense"

    for rule in sorted(rules, key=rule_order):
        # Built-in rules for categories in `exclude` are skipped; user rules never are.
        if rule.category in exclude and not rule.is_user_defined:
            continue
        if rule_matches(rule, merchant, description, amount_minor):
            return rule.category

    from_network = category_from_merchant_category(merchant_category)
    if from_network and from_network not in exclude:
        return from_network
    return default


# Card networks' merchant categories (MCC descriptions such as "GROCERY
# STORES/SUPERMARKETS", "PASSENGER RAILWAYS") -> category. Checked in this
# order; groups that don't say what was bought ("WIRE TRANSFER MONEY
# ORDER", "COMPUTER PROGRAM/SYS DESIGN", "QUICK COPY") stay unmapped.
MERCHANT_CATEGORY_RULES: list[tuple[str, str]] = [
    (r"grocer|supermarket|food stores|misc food|convenience store|dairy|meat provision|candy|lebensmittel|supermarkt",
     "Groceries"),
    (r"restaurant|fast food|eating place|caterer|baker|\bbars?\b|tavern|coffee|gastst|imbiss", "Food"),
    (r"pharmac|drug stores?|doctor|physician|dentist|orthodont|optician|optometr|hospital|medical|apothek", "Health"),
    (r"railway|passenger|commuter|transit|bus lines|taxi|limousine|parking|garages|service station|fuel|petroleum"
     r"|car wash|automotive|toll|ferr(?:y|ies)|tankstell", "Transport"),
    (r"airline|air carrier|airport|hotel|motel|resort|lodging|travel agenc|tour operator|car rental|cruise", "Travel"),
    (r"amusement|theat|cinema|motion picture|recreation|sports club|athletic field|bowling|golf|museum"
     r"|tourist attraction|ticket agenc", "Entertainment"),
    (r"school|college|universit|education|child care", "Education"),
    (r"telecommunication service|telephone service|utilit|electric service|cable", "Utilities"),
    (r"insurance", "Insurance"),
    (r"charitable|religious organi", "Donations"),
    (r"cash disburse|manual cash|automated cash", "Cash"),
    (r"stores?\b|shops?\b|retail|clothing|apparel|department|discount|sporting goods|furniture|electronics"
     r"|hardware|jewel|toy|hobby|gift|florist|equipment", "Shopping"),
]


def category_from_merchant_category(merchant_category: str | None) -> str | None:
    if not merchant_category:
        return None
    for pattern, category in MERCHANT_CATEGORY_RULES:
        if re.search(pattern, merchant_category, re.IGNORECASE):
            return category
    return None


def rule_order(rule: CategoryRule) -> tuple:
    """User rules first. Among them the most specific (longest pattern)
    wins, then the most recent — so teaching "REWE Getränke" -> Drinks after
    "REWE" -> Groceries works, and re-teaching a pattern replaces it.
    Built-in rules follow in priority order."""
    if rule.is_user_defined:
        return (0, rule.priority, -len(rule.pattern or ""), -(rule.id or 0))
    return (1, rule.priority, 0, rule.id or 0)


def rule_could_match(rule: CategoryRule, lowered_text: str) -> bool:
    """Cheap pre-check before rule_matches: a plain pattern must at least
    occur in the (lower-cased merchant + description) text."""
    return rule.is_regex or rule.pattern.lower() in lowered_text


def rule_matches(rule: CategoryRule, merchant: str | None, description: str | None, amount_minor: int) -> bool:
    if not _sign_matches(rule, amount_minor):
        return False
    if rule.match_field == "merchant":
        values = [merchant]
    elif rule.match_field == "description":
        values = [description]
    else:  # "any"
        values = [merchant, description]
    for field_value in values:
        if not field_value:
            continue
        try:
            if rule.is_regex:
                if re.search(rule.pattern, field_value, re.IGNORECASE):
                    return True
            # A plain pattern must match whole words: "REWE" is not in "Brewery".
            elif re.search(rf"(?<!\w){re.escape(rule.pattern)}(?!\w)", field_value, re.IGNORECASE):
                return True
        except re.error:
            return False
    return False
