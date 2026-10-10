"""Address matching against VARIS (PLAN.md §5.1).

Order: existing (EKS) addresses by their current text or an earlier text of
the same code; only if none qualifies, deleted (DEL) addresses. ERR addresses
are never imported, so they can never match.

Retrieval (SQL): every typed word except place names and street-type words
must reach pg_trgm word_similarity with the stored search key (ref.addr_key);
a named pilot city filters by ATVK. Ranking (Python): how well the typed
words cover the address words and the reverse, with house numbers compared
exactly. Only a clear winner with the typed house number resolves without
asking (thresholds in config/resolve.yaml).
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache

from psycopg import sql

from engine.resolve import notes
from engine.resolve.context import AddressSettings, Versions
from engine.resolve.models import AddressRef, Match, Note, Suggestion
from engine.resolve.places import KEY_DROP, STREET_WORDS, Places, PlaceScan, scan

TIER_LABEL = {"current": "exact", "earlier": "earlier_name", "deleted": "historical"}


@dataclass
class Candidate:
    code: str
    status: str  # EKS | DEL
    matched_text: str  # the text that matched (current or earlier)
    matched_norm: str
    full_text: str  # the address's current text
    city_atvk: str
    tier: str  # current | earlier | deleted
    score: float = 0.0
    numbers_ok: bool = False
    exact: bool = False  # normalised input == normalised matched text
    words_exact: bool = False  # every typed word is a word of the address


@dataclass
class Query:
    raw: str
    norm: str
    places: PlaceScan
    words: list[str]
    numbers: list[str]
    prefix: bool  # type-ahead: the last word may be incomplete
    vocabulary: frozenset[str] = frozenset()

    @property
    def retrieval_words(self) -> list[str]:
        """Typed words used to find candidates. Street-type words are left out
        (the search key has none), and so is a word that only looks like one
        being typed or misspelt ('ie', 'iel', 'prospeks') - unless some
        address has that word ('lauku' is a street, not 'laukums' half-typed)."""
        return [
            w
            for w in self.words
            if len(w) >= 2
            and w not in KEY_DROP
            and (w in self.vocabulary or not _street_word_like(w))
        ]


def _street_word_like(w: str) -> bool:
    return any(k.startswith(w) or (k[0] == w[0] and _ratio(w, k) >= 0.8) for k in KEY_DROP)


_vocabulary: dict[tuple, frozenset[str]] = {}


def vocabulary(conn, v: Versions) -> frozenset[str]:
    """Every word of the address search keys (current and earlier texts),
    cached per database and VARIS version."""
    key = (conn.info.host, conn.info.port, conn.info.dbname, v.varis_addresses)
    words = _vocabulary.get(key)
    if words is None:
        words = frozenset(
            r[0]
            for r in conn.execute(
                """SELECT unnest(string_to_array(norm_key, ' ')) FROM ref.address
                   WHERE dataset_version_id = %(v)s
                   UNION
                   SELECT unnest(string_to_array(norm_key, ' ')) FROM ref.address_history
                   WHERE dataset_version_id = %(v)s""",
                {"v": v.varis_addresses},
            )
        )
        _vocabulary.clear()
        _vocabulary[key] = words
    return words


@dataclass
class AddressDecision:
    status: str
    matches: list[Match] = field(default_factory=list)
    warnings: list[Note] = field(default_factory=list)
    reason: str | None = None
    resolved_code: str | None = None  # EKS address whose objects are the result


def parse(conn, v: Versions, places: Places, cfg: AddressSettings, raw: str, prefix: bool) -> Query:
    norm = conn.execute("SELECT ref.addr_norm(%s)", (raw,)).fetchone()[0] or ""
    found = scan(norm, places, cfg.pilot_city_fuzzy)
    words = [t for t in found.tokens if not any(ch.isdigit() for ch in t)]
    numbers = [t for t in found.tokens if any(ch.isdigit() for ch in t)]
    return Query(
        raw=raw,
        norm=norm,
        places=found,
        words=words,
        numbers=numbers,
        prefix=prefix,
        vocabulary=vocabulary(conn, v),
    )


# --- retrieval ------------------------------------------------------------------------


def _retrieve(
    conn, v: Versions, q: Query, city_atvk: str | None, cfg: AddressSettings
) -> list[Candidate]:
    words = q.retrieval_words
    if not words:
        return []
    params: dict = {
        "v": v.varis_addresses,
        "q": " ".join(q.words + q.numbers),
        "n": cfg.max_candidates,
    }
    conds = []
    for i, w in enumerate(words):
        params[f"w{i}"] = w
        conds.append(sql.SQL("{} <%% x.norm_key").format(sql.Placeholder(f"w{i}")))
    order = sql.SQL("word_similarity(%(q)s, x.norm) DESC")
    if q.numbers:  # rows with the typed house number first
        params["nre"] = r"\m(" + "|".join(q.numbers) + r")\M"
        order = sql.SQL("(x.norm ~ %(nre)s) DESC, ") + order
    city = sql.SQL("")
    if city_atvk:
        params["city"] = city_atvk
        city = sql.SQL("AND a.city_atvk = %(city)s")
    where = sql.SQL(" AND ").join(conds)

    query = sql.SQL(
        """
        (SELECT a.code, a.status, a.full_text, x.norm, a.full_text, a.city_atvk,
                CASE a.status WHEN 'EKS' THEN 'current' ELSE 'deleted' END
         FROM ref.address a, LATERAL (SELECT a.norm, a.norm_key) x
         WHERE a.dataset_version_id = %(v)s AND {where} {city}
         ORDER BY {order} LIMIT %(n)s)
        UNION ALL
        (SELECT a.code, a.status, h.full_text, x.norm, a.full_text, a.city_atvk,
                CASE a.status WHEN 'EKS' THEN 'earlier' ELSE 'deleted' END
         FROM ref.address_history h
         JOIN ref.address a ON a.dataset_version_id = h.dataset_version_id AND a.code = h.code,
         LATERAL (SELECT h.norm, h.norm_key) x
         WHERE h.dataset_version_id = %(v)s AND {where} {city}
         ORDER BY {order} LIMIT %(n)s)
        """
    ).format(where=where, city=city, order=order)
    conn.execute(
        "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)",
        (str(cfg.retrieval_threshold),),
    )
    return [Candidate(*row) for row in conn.execute(query, params)]


def candidates(conn, v: Versions, places: Places, cfg: AddressSettings, q: Query):
    """Scored candidates, best first, one per (code, tier); and whether the city
    filter had to be dropped (a pilot city was named but nothing matched in it)."""
    city = q.places.pilot_city.atvk if q.places.pilot_city else None
    rows = _retrieve(conn, v, q, city, cfg)
    city_dropped = False
    if not rows and city:
        rows = _retrieve(conn, v, q, None, cfg)
        city_dropped = bool(rows)
    city_norms = {atvk: _norm_city(places, atvk) for atvk in {r.city_atvk for r in rows}}
    best: dict[tuple[str, str], Candidate] = {}
    for c in rows:
        _score(c, q, city_norms.get(c.city_atvk), cfg.word_match)
        key = (c.code, "deleted" if c.status == "DEL" else "existing")
        old = best.get(key)
        if old is None or (c.score, c.tier == "current") > (old.score, old.tier == "current"):
            best[key] = c
    ranked = sorted(
        best.values(),
        key=lambda c: (-c.score, not c.words_exact, c.tier != "current", c.full_text),
    )
    return ranked, city_dropped


def _norm_city(places: Places, atvk: str) -> str | None:
    for p in places.pilot_cities:
        if p.atvk == atvk:
            return p.norm
    return None


# --- scoring ----------------------------------------------------------------------------


@lru_cache(maxsize=65536)
def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _word_score(w: str, cand_words: list[str], prefix: bool) -> float:
    if prefix and any(cw.startswith(w) for cw in cand_words):
        return 1.0
    return max((_ratio(w, cw) for cw in cand_words), default=0.0)


def _score(c: Candidate, q: Query, city_norm: str | None, word_match: float) -> None:
    tokens = [t for t in c.matched_norm.split() if t != city_norm]
    cand_words = [t for t in tokens if not any(ch.isdigit() for ch in t)]
    # street-type words the input left out do not count against it
    own_words = [t for t in cand_words if t not in STREET_WORDS or t in q.words]
    cand_numbers = [t for t in tokens if any(ch.isdigit() for ch in t)]
    if q.words:
        scores = [
            _word_score(w, cand_words, q.prefix and i == len(q.words) - 1 and not q.numbers)
            for i, w in enumerate(q.words)
        ]
        q_cov = sum(scores) / len(scores)
    else:
        q_cov = 0.0
    typing = q.words[-1] if q.prefix and q.words else None
    covered = sum(
        1
        for cw in own_words
        if any(_ratio(w, cw) >= word_match for w in q.words)
        or (typing is not None and cw.startswith(typing))
    )
    c_cov = covered / len(own_words) if own_words else 1.0
    score = 0.85 * q_cov + 0.15 * c_cov
    numbers_ok = sorted(q.numbers) == sorted(cand_numbers)
    if q.prefix and not numbers_ok:
        # type-ahead: no number typed yet, or the last one still being typed
        *whole, last = q.numbers or [""]
        if all(n in cand_numbers for n in whole) and any(n.startswith(last) for n in cand_numbers):
            score *= 0.97 if q.numbers else 1.0
            numbers_ok = True
    if not numbers_ok:
        score *= 0.7
    c.score = round(score, 4)
    c.numbers_ok = numbers_ok
    c.exact = q.norm == c.matched_norm
    c.words_exact = bool(q.words) and all(w in cand_words for w in q.words)


# --- decision ---------------------------------------------------------------------------


def links(conn, v: Versions, places: Places, code: str) -> list[AddressRef]:
    """Existing addresses linked to `code` through aw_eka_his.KODS_HIS, either
    direction (docs/data-sources.md §3.1)."""
    rows = conn.execute(
        """SELECT DISTINCT a.code, a.full_text, a.city_atvk
           FROM ref.address_history h
           JOIN ref.address a ON a.dataset_version_id = h.dataset_version_id
                AND a.status = 'EKS'
                AND a.code = CASE WHEN h.code = %(c)s THEN h.code_his ELSE h.code END
           WHERE h.dataset_version_id = %(v)s AND h.code_his IS NOT NULL
             AND (h.code = %(c)s OR h.code_his = %(c)s)
           ORDER BY a.full_text""",
        {"v": v.varis_addresses, "c": code},
    ).fetchall()
    return [
        AddressRef(varis_code=c, full_text=t, status="EKS", city=places.city_by_atvk.get(a))
        for c, t, a in rows
    ]


def _ref(c: Candidate, places: Places) -> AddressRef:
    return AddressRef(
        varis_code=c.code,
        full_text=c.full_text,
        status=c.status,
        city=places.city_by_atvk.get(c.city_atvk),
    )


def _as_match(c: Candidate, places: Places, match_type: str | None = None) -> Match:
    return Match(
        type="address",
        designation=c.code,
        label="Adrese",
        description=c.matched_text if c.tier == "earlier" else c.full_text,
        match_type=match_type or ("fuzzy" if not c.exact and c.tier == "current" else
                                  TIER_LABEL[c.tier]),
        score=c.score,
        address=_ref(c, places),
    )  # fmt: skip


def _clear_winner(pool: list[Candidate], cfg: AddressSettings, city_dropped: bool) -> bool:
    if not pool or city_dropped:
        return False
    best = pool[0]
    if not best.numbers_ok or best.score < cfg.auto_resolve_score:
        return False
    rivals = [c for c in pool[1:] if c.code != best.code]
    if not rivals or best.score - rivals[0].score >= cfg.auto_resolve_margin:
        return True
    # near-identical street names ('Ārijas' / 'Marijas'): the only candidate
    # with every typed word spelt as typed and the typed number wins
    return best.words_exact and not any(c.words_exact and c.numbers_ok for c in rivals)


def decide(
    conn, v: Versions, places: Places, cfg: AddressSettings, raw: str
) -> tuple[AddressDecision, Query]:
    q = parse(conn, v, places, cfg, raw, prefix=False)
    outside = q.places.outside_pilot
    if outside is not None:
        return AddressDecision(status="outside_pilot", reason=notes.outside_pilot(outside.name)), q
    ranked, city_dropped = candidates(conn, v, places, cfg, q)
    existing = [c for c in ranked if c.status == "EKS"]
    deleted = [c for c in ranked if c.status == "DEL"]

    if _clear_winner(existing, cfg, city_dropped):
        best = existing[0]
        warnings = []
        if not best.exact:
            warnings.append(notes.fuzzy_address(raw, best.matched_text))
        if best.tier == "earlier":
            warnings.append(notes.earlier_name(best.full_text))
        match = _as_match(best, places)
        match.warnings = warnings
        return AddressDecision(
            status="resolved", matches=[match], warnings=warnings, resolved_code=best.code
        ), q

    if ranked and ranked[0].status == "DEL" and _clear_winner(ranked, cfg, city_dropped):
        best = ranked[0]
        warnings = [] if best.exact else [notes.fuzzy_address(raw, best.matched_text)]
        deleted = _as_match(best, places, "historical")
        return _deleted(conn, v, places, deleted, warnings), q

    shortlist = (existing + deleted)[: cfg.suggest_limit]
    if not shortlist:
        return AddressDecision(status="not_found", reason="adrese pilota datos nav atrasta"), q
    warnings = []
    if city_dropped:
        warnings.append(
            Note(
                code="city_mismatch",
                message=f"{q.places.pilot_city.name}: šādas adreses nav; ieteikumi citās pilsētās",
            )
        )
    return AddressDecision(
        status="ambiguous",
        matches=[_as_match(c, places) for c in shortlist],
        warnings=warnings,
        reason="adrese nav viennozīmīgi atrasta; izvēlieties no ieteikumiem",
    ), q


def _deleted(
    conn, v: Versions, places: Places, deleted: Match, warnings: list[Note]
) -> AddressDecision:
    """A deleted address: resolved to its one KODS_HIS successor, ambiguous with
    several, not resolved with none (PLAN.md §5.1 step 2)."""
    warnings = [*warnings, notes.historical_address()]
    current = links(conn, v, places, deleted.designation)
    if not current:
        return AddressDecision(
            status="unresolved",
            matches=[deleted],
            warnings=[*warnings, notes.current_unknown()],
            reason="vēsturiska adrese; pašreizējā adrese nav zināma",
        )
    matches = [
        Match(
            type="address",
            designation=ref.varis_code,
            label="Adrese",
            description=ref.full_text,
            match_type="historical",
            address=ref,
            warnings=[notes.current_address(ref.full_text)],
        )
        for ref in current
    ]
    warnings += [notes.current_address(ref.full_text) for ref in current]
    if len(current) == 1:
        return AddressDecision(
            status="resolved",
            matches=[*matches, deleted],
            warnings=warnings,
            resolved_code=current[0].varis_code,
        )
    return AddressDecision(
        status="ambiguous",
        matches=[*matches, deleted],
        warnings=warnings,
        reason=f"vēsturiska adrese sadalīta {len(current)} pašreizējās adresēs; izvēlieties",
    )


def by_code(conn, v: Versions, places: Places, code: str) -> AddressDecision:
    """A VARIS address code typed instead of an address."""
    row = conn.execute(
        "SELECT full_text, status, city_atvk FROM ref.address"
        " WHERE dataset_version_id = %s AND code = %s",
        (v.varis_addresses, code),
    ).fetchone()
    if row is None:
        return AddressDecision(
            status="not_found", reason=f"adrese {code} pilota adrešu datos nav atrasta"
        )
    full_text, status, atvk = row
    match = Match(
        type="address",
        designation=code,
        label="Adrese",
        description=full_text,
        match_type="exact" if status == "EKS" else "historical",
        address=AddressRef(
            varis_code=code, full_text=full_text, status=status, city=places.city_by_atvk.get(atvk)
        ),
    )
    if status == "DEL":
        return _deleted(conn, v, places, match, [])
    return AddressDecision(status="resolved", matches=[match], resolved_code=code)


# --- type-ahead ---------------------------------------------------------------------------


def suggest(
    conn, v: Versions, places: Places, cfg: AddressSettings, raw: str
) -> tuple[list[Suggestion], list[Note]]:
    q = parse(conn, v, places, cfg, raw, prefix=True)
    notices = []
    outside = q.places.outside_pilot
    if outside is not None:
        notices.append(Note(code="outside_pilot", message=notes.outside_pilot(outside.name)))
    ranked, city_dropped = candidates(conn, v, places, cfg, q)
    if city_dropped:
        notices.append(
            Note(
                code="city_mismatch",
                message=f"{q.places.pilot_city.name}: šādas adreses nav; ieteikumi citās pilsētās",
            )
        )
    out = []
    for c in ranked[: cfg.suggest_limit]:
        city = places.city_by_atvk.get(c.city_atvk)
        label = c.matched_text
        if city and city not in label:
            label = f"{label}, {city}"
        current = None
        if c.tier == "earlier":
            current = c.full_text
        elif c.status == "DEL":
            current = "; ".join(r.full_text for r in links(conn, v, places, c.code)) or None
        out.append(
            Suggestion(
                type="address",
                designation=c.code,
                label=label,
                description=None,
                city=city,
                match_type=_as_match(c, places).match_type,
                score=c.score,
                status=c.status,
                current_address=current,
            )
        )
    return out, notices
