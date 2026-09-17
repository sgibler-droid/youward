#!/usr/bin/env python3
"""
YouWard status verification sweep  (v4, 2026-09-14)

Ported from verify-status.py v4 (sha256 b727c1cd041362dd2e3d370be153d42e273f15ab8f914a09faa145bb8d788656).
Runs in GitHub Actions. Reads the live v1 page, checks every record against its
official source, and may change only each record's status cell and data-evidence
attribute. It never adds, removes, or redesigns records.

v2 fixes, all driven by the Sep 14 diagnostics:
  - grants.gov date parsing was the whole bug. `synopsis.responseDate` was
    present all along, formatted 'Sep 07, 2027 12:00:00 AM EDT', which none of
    v1's three date formats matched, so every grant fell through to "no usable
    close date". v2 prefers the machine-readable `responseDateStr`
    ('2027-09-07-00-00-00') and falls back across formats.
  - Adds the authoritative signal: search2 by `oppNum` returns `oppStatus`
    (posted / forecasted / closed / archived) per opportunity.
  - Guards two traps found in diagnostics:
      * search2 keyword matching is unreliable (an exact title returned a
        different opportunity out of 1516 hits). Only oppNum is used, and hits
        are matched back on opportunity id.
      * search2 defaults oppStatuses to 'forecasted|posted', silently hiding
        closed and archived. All four are always passed explicitly.
  - Adds a fourth page state, `upcoming`, for forecasted opportunities. They are
    neither open nor closed and labelling them either way is false.
  - The v1 page already renders all four states. This port never patches page
    structure, CSS, JavaScript, records, or any field other than status/evidence.

Standing rules this obeys:
  - A future deadline NEVER establishes "open". Only a positive status signal
    does. This is the ACL Caregiver defect: usa.gov showed a 2029 end date while
    the agency had closed Phase 1 on 2026-07-31.
  - Anything not positively resolved stays `unverified`, never `open`.
  - Every status carries evidence: source, date checked, what it said.
  - Evidence strings never embed raw API bodies (those carry publisherUid and
    bearer-like tokens). Field-scoped values only.
  - Read-only against the web. Writes only a candidate page, receipt, and ledger.
  - A fetch failure keeps the prior status once, then becomes unverified after
    two consecutive failures. The counter is encoded in data-evidence.
  - A run changing more than 20% of statuses is blocked before page output unless
    a human clearance reference is supplied.
  - This script never commits or pushes.

Usage:
    python3 scripts/verify-status.py --html index.html --out /tmp/index.next.html --dry-run
    python3 scripts/verify-status.py --html index.html --out index.html --breaker-clearance '<Slack receipt>'
"""

import argparse, datetime, html as H, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

TODAY = datetime.date.today()
UA = "YouWard-status-audit/2.0 (public program status verification)"
DELAY = 1.2
TIMEOUT = 25
STATES = ("open", "closed", "upcoming", "unverified")
EXPECTED_RECORDS = 199
BREAKER_RATIO = 0.20
BREAKER_EXIT = 42
FAILURE_COUNT_RX = re.compile(r"^\[FETCH_FAILURE_COUNT=(\d+)\]\s*")
FETCH_FAILURE_MARKERS = (
    "fetch returned", "api error", "response was not json", "error ",
    "timed out", "temporary failure", "name or service not known",
    "connection reset", "connection refused", "too many redirects",
)

# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"ERROR {e}"

def post_json(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

def text_of(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", html)))

# --------------------------------------------------------------------------
# date parsing  (v1's actual defect)
# --------------------------------------------------------------------------

DATE_FORMATS = (
    "%Y-%m-%d-%H-%M-%S",          # responseDateStr / archiveDateStr
    "%b %d, %Y %I:%M:%S %p",      # 'Sep 07, 2027 12:00:00 AM' after tz strip
    "%b %d, %Y",
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%B %d %Y",
    "%b %d %Y",
)

def parse_gov_date(value):
    """Return a date, or None. Tolerates trailing timezone abbreviations."""
    if not value or not str(value).strip():
        return None
    s = str(value).strip()
    s = re.sub(r"\s+(EDT|EST|CDT|CST|MDT|MST|PDT|PST|UTC|GMT)$", "", s)
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime.date(*map(int, m.groups()))
        except ValueError:
            pass
    return None

# --------------------------------------------------------------------------
# resolvers -> (status, evidence)
# --------------------------------------------------------------------------

OPP_STATUS_MAP = {"posted": "open", "closed": "closed",
                  "archived": "closed", "forecasted": "upcoming"}

def resolve_grants_gov(url):
    oid = re.search(r"/search-results-detail/(\d+)", url)
    if not oid:
        return "unverified", f"{url} | checked {TODAY} | could not parse opportunity id"
    oid = oid.group(1)

    try:
        d = post_json("https://api.grants.gov/v1/api/fetchOpportunity",
                      {"opportunityId": int(oid)})
    except Exception as e:
        return "unverified", f"grants.gov fetchOpportunity id {oid} | checked {TODAY} | API error {e}"

    if d.get("errorcode") not in (0, None):
        return "unverified", (f"grants.gov fetchOpportunity id {oid} | checked {TODAY} | "
                              f"API errorcode {d.get('errorcode')}: {str(d.get('msg'))[:80]}")

    data = d.get("data") or {}
    syn = data.get("synopsis") or {}
    oppnum = data.get("opportunityNumber") or ""
    resp = parse_gov_date(syn.get("responseDateStr") or syn.get("responseDate"))
    arch = parse_gov_date(syn.get("archiveDateStr") or syn.get("archiveDate"))
    desc = (syn.get("responseDateDesc") or "").strip()
    rolling = "anytime" in (data.get("originalDueDateDesc") or "").lower()

    # authoritative signal: oppStatus, matched back to this opportunity id
    opp_status = None
    if oppnum:
        try:
            time.sleep(DELAY)
            s = post_json("https://api.grants.gov/v1/api/search2",
                          {"oppNum": oppnum,
                           "oppStatuses": "forecasted|posted|closed|archived",
                           "rows": 25})
            for h in ((s.get("data") or {}).get("oppHits") or []):
                if str(h.get("id")) == str(oid):
                    opp_status = (h.get("oppStatus") or "").lower()
                    break
        except Exception:
            opp_status = None

    detail = (f"oppNum {oppnum}" if oppnum else f"id {oid}")
    if resp:    detail += f", response date {resp.isoformat()}"
    if arch:    detail += f", archive date {arch.isoformat()}"
    if rolling: detail += ", proposals accepted anytime"

    if opp_status in OPP_STATUS_MAP:
        mapped = OPP_STATUS_MAP[opp_status]
        # grants.gov sometimes leaves an expired opportunity flagged posted
        if mapped == "open" and resp and resp < TODAY:
            return "closed", (f"grants.gov API id {oid} | checked {TODAY} | oppStatus '{opp_status}' "
                              f"but response date {resp.isoformat()} has passed; treated as closed ({detail})")
        if mapped == "open" and arch and arch < TODAY:
            return "closed", (f"grants.gov API id {oid} | checked {TODAY} | oppStatus '{opp_status}' "
                              f"but archive date {arch.isoformat()} has passed; treated as closed ({detail})")
        return mapped, f"grants.gov API id {oid} | checked {TODAY} | oppStatus '{opp_status}' ({detail})"

    # no oppStatus: fall back to explicit agency wording, then dates
    low = desc.lower()
    if desc and ("not accepted" in low or "archived" in low or "closed" in low):
        return "closed", (f"grants.gov API id {oid} | checked {TODAY} | "
                          f"responseDateDesc: '{desc[:110]}' ({detail})")
    if arch and arch < TODAY:
        return "closed", (f"grants.gov API id {oid} | checked {TODAY} | "
                          f"archive date {arch.isoformat()} has passed ({detail})")
    if resp and resp < TODAY:
        return "closed", (f"grants.gov API id {oid} | checked {TODAY} | "
                          f"response date {resp.isoformat()} has passed ({detail})")
    return "unverified", (f"grants.gov API id {oid} | checked {TODAY} | no oppStatus match and no expired "
                          f"date; a future date alone does not establish open ({detail})")

CLOSED_HINTS = ["no longer accepting", "submissions are closed", "competition has closed",
                "challenge is closed", "closed to submissions", "applications are closed",
                "this opportunity is closed", "winners announced", "submission period has ended"]
OPEN_HINTS = ["now accepting", "currently accepting", "open for submissions",
              "accepting applications", "accepting submissions"]

MONTH_RX = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}", re.I)
DUE_RX = re.compile(
    r"(applications?\s+due|submissions?\s+due|entries\s+due|proposals?\s+due|"
    r"deadline|due|closes|closing|close\s+date|submitted\s+by|submit\s+by|"
    r"no\s+later\s+than|must\s+be\s+received)", re.I)

def collect_due_dates(t):
    """Dates on a page that are labelled as a due date.

    A keyword may sit either side of the date ('Phase 1 Applications Due' after,
    'submissions due' before), so both are checked. Each window is bounded by the
    neighbouring dates, so a keyword belonging to a different line cannot be
    attributed to this one. That mis-attribution silently broke the v3 guard: on
    the ACL Caregiver page a forward-only window starting at 'May 28, 2026' ran
    into 'Phase 1 Applications Due' and captured the wrong date, while the real
    due date of July 31 was never collected at all.
    """
    spans = [(m.start(), m.end(), m.group(0)) for m in MONTH_RX.finditer(t)]
    dues = []
    for i, (start, end, raw) in enumerate(spans):
        prev_end = spans[i - 1][1] if i else 0
        next_start = spans[i + 1][0] if i + 1 < len(spans) else len(t)
        after = t[end:min(next_start, end + 120)]
        before = t[max(prev_end, start - 90):start]
        if DUE_RX.search(after) or DUE_RX.search(before):
            d = parse_gov_date(re.sub(r"\s+", " ", raw).replace(",", ""))
            if d:
                dues.append(d)
    return dues

def collect_all_dates(t):
    """Every parseable date on the page, keyword or not.

    Deliberately high-recall. Used only to VETO the weak 'closed_hit' path: if any
    future date appears anywhere on an agency page, a phrase like 'winners
    announced' is not sufficient to declare the whole competition closed, because
    a later phase may still be accepting. Over-collecting here costs an
    'unverified', which is recoverable. Under-collecting costs a false 'closed',
    which tells someone a live opportunity is dead.
    """
    out = []
    for m in MONTH_RX.finditer(t):
        d = parse_gov_date(re.sub(r"\s+", " ", m.group(0)).replace(",", ""))
        if d:
            out.append(d)
    return out

def resolve_usagov_challenge(url):
    """The aggregator is stale by design; use it only to reach the hosting agency."""
    code, body = get(url)
    if code == 404:
        return "closed", (f"{url} | checked {TODAY} | listing returns 404; the record is no longer "
                          f"present in USAGov's index of active challenges")
    if code != 200:
        return "unverified", f"{url} | checked {TODAY} | fetch returned {code}"
    end = re.search(r"End date\s*\|\s*([^|\n]+)", text_of(body))
    end_txt = end.group(1).strip() if end else "not stated"

    m = re.search(r'href="(https?://(?!www\.usa\.gov)[^"]+)"[^>]*>\s*Apply for', body)
    if not m:
        m = re.search(r'href="(https?://[^"]*\.gov/[^"]*(?:challenge|competition|prize)[^"]*)"', body)
    if not m:
        return "unverified", (f"{url} | checked {TODAY} | aggregator end date {end_txt}; no hosting-agency "
                              f"link found, so submission status not established")

    agency = m.group(1)
    time.sleep(DELAY)
    acode, abody = get(agency)
    if acode != 200:
        return "unverified", (f"{agency} | checked {TODAY} | fetch returned {acode}; aggregator lists "
                              f"end date {end_txt}, which does not establish open")

    t = text_of(abody)
    low = t.lower()
    dues = collect_due_dates(t)
    all_dates = collect_all_dates(t)

    closed_hit = next((h for h in CLOSED_HINTS if h in low), None)
    open_hit = next((h for h in OPEN_HINTS if h in low), None)

    seen = ", ".join(d.isoformat() for d in sorted(set(dues))) if dues else "none parsed"
    future_dues = [d for d in dues if d >= TODAY]

    if dues and not future_dues:
        return "closed", (f"{agency} | checked {TODAY} | latest stated due date {max(dues).isoformat()} "
                          f"has passed (dates on page: {seen}); aggregator shows end date {end_txt}")
    future_any = sorted({d for d in all_dates if d >= TODAY})
    if closed_hit and (future_dues or future_any):
        nxt = min(future_dues) if future_dues else future_any[0]
        return "unverified", (f"{agency} | checked {TODAY} | page states '{closed_hit}' but also carries a "
                              f"future date {nxt.isoformat()} (due dates: {seen}); possibly a later phase "
                              f"still accepting, needs a human read")
    if closed_hit and not open_hit:
        return "closed", (f"{agency} | checked {TODAY} | agency page states '{closed_hit}'; no future date "
                          f"appears anywhere on the page (due dates: {seen})")
    if open_hit and dues and max(dues) >= TODAY:
        return "open", (f"{agency} | checked {TODAY} | agency page states '{open_hit}' with due date "
                        f"{max(dues).isoformat()} still ahead")
    return "unverified", (f"{agency} | checked {TODAY} | no unambiguous submission-status signal "
                          f"(aggregator end date {end_txt}); needs a human read")

def resolve_fbi(url):
    code, body = get(url)
    if code == 404:
        return "closed", f"{url} | checked {TODAY} | record no longer published (404)"
    if code != 200:
        return "unverified", f"{url} | checked {TODAY} | fetch returned {code}"
    try:
        d = json.loads(body)
    except Exception:
        return "unverified", f"{url} | checked {TODAY} | response was not JSON"
    status = (d.get("status") or "").lower()
    if status in ("captured", "located", "recovered", "deceased", "removed", "resolved"):
        return "closed", f"{url} | checked {TODAY} | FBI record status '{status}'"
    if d.get("reward_text") or d.get("reward_min"):
        return "open", (f"{url} | checked {TODAY} | record still published"
                        + (f" (status '{status}')" if status else "") + "; reward still listed")
    return "unverified", f"{url} | checked {TODAY} | published but no reward field found; needs a human read"

def resolve(url):
    if "usa.gov/challenges" in url: return resolve_usagov_challenge(url)
    if "grants.gov" in url:         return resolve_grants_gov(url)
    if "fbi.gov" in url:            return resolve_fbi(url)
    return "unverified", f"{url} | checked {TODAY} | no resolver for this source domain"

# --------------------------------------------------------------------------
# bounded state machine and mutation guard
# --------------------------------------------------------------------------

def is_fetch_failure(evidence):
    low = evidence.lower()
    return any(marker in low for marker in FETCH_FAILURE_MARKERS)


def prior_failure_count(evidence):
    m = FAILURE_COUNT_RX.match(evidence or "")
    return int(m.group(1)) if m else 0


def stable_prior_evidence(evidence):
    value = FAILURE_COUNT_RX.sub("", evidence or "")
    return value.split(" || FETCH_FAILURE checked ", 1)[0].strip()


def apply_resolution(prior_status, prior_evidence, resolved_status, resolved_evidence, today=None):
    """Apply the two-failure rule without allowing failure to create an open."""
    today = today or TODAY
    prior_status = prior_status if prior_status in STATES else "unverified"
    if is_fetch_failure(resolved_evidence):
        count = prior_failure_count(prior_evidence) + 1
        base = stable_prior_evidence(prior_evidence) or "no prior evidence recorded"
        evidence = (f"[FETCH_FAILURE_COUNT={count}] {base} || FETCH_FAILURE checked {today}: "
                    f"{resolved_evidence}")
        status = prior_status if count < 2 else "unverified"
        return status, evidence

    if resolved_status == "unverified" and prior_status in ("open", "closed", "upcoming"):
        evidence = (f"KEPT PRIOR VERDICT '{prior_status}' because the re-check was inconclusive. "
                    f"Prior: {stable_prior_evidence(prior_evidence) or '(no prior evidence recorded)'} "
                    f"|| Re-check {today}: {resolved_evidence}")
        return prior_status, evidence
    return resolved_status, resolved_evidence


def breaker_tripped(status_changes, total):
    return bool(total) and status_changes / total > BREAKER_RATIO


def mask_mutable_fields(row):
    masked = re.sub(r'\sdata-evidence="[^"]*"', ' data-evidence="__EVIDENCE__"', row)
    return re.sub(r'(<td[^>]*>)(?!.*<td)(.*?)(</td>\s*</tr>\s*$)',
                  r'\1__STATUS__\3', masked, count=1, flags=re.S)


def rewrite_row(row, status, evidence):
    updated = re.sub(r'(<td[^>]*>)(?!.*<td)(.*?)(</td>\s*</tr>\s*$)',
                     lambda m: m.group(1) + status + m.group(3),
                     row, count=1, flags=re.S)
    updated = re.sub(r'\sdata-evidence="[^"]*"', "", updated)
    updated = updated.replace('<tr class="rec"',
                              f'<tr class="rec" data-evidence="{H.escape(evidence, quote=True)}"', 1)
    if mask_mutable_fields(row) != mask_mutable_fields(updated):
        raise RuntimeError("record mutation exceeded status/evidence fields")
    return updated

# --------------------------------------------------------------------------

def main():
    global TODAY
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="index.html")
    ap.add_argument("--out", default="")
    ap.add_argument("--ledger", default="status-ledger.json")
    ap.add_argument("--receipt", default="status-receipt.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--breaker-clearance", default="")
    ap.add_argument("--expected-records", type=int, default=EXPECTED_RECORDS)
    ap.add_argument("--today", default="")
    a = ap.parse_args()
    if a.today:
        TODAY = datetime.date.fromisoformat(a.today)

    s = Path(a.html).read_text(encoding="utf-8")
    tb = re.search(r"(<tbody>)(.*?)(</tbody>)", s, re.S)
    if not tb:
        sys.exit("no <tbody> found")
    rows = re.findall(r"<tr\b.*?</tr>", tb.group(2), re.S)
    if len(rows) != a.expected_records:
        sys.exit(f"record-count invariant failed: expected {a.expected_records}, found {len(rows)}")
    print(f"{len(rows)} records in {a.html}  |  today {TODAY}")
    if a.only:  print(f"restricted to class: {a.only}")
    if a.limit: print(f"checking at most {a.limit} this run")
    print()

    out, ledger, counts, checked = [], [], {k: 0 for k in STATES}, 0
    status_changes = evidence_changes = 0
    for i, row in enumerate(rows, 1):
        cm = re.search(r'data-class="([^"]+)"', row)
        cls = cm.group(1) if cm else ""
        href = re.search(r'href="([^"]+)"', row)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if not tds:
            sys.exit(f"record {i} has no cells")
        title = re.sub(r"<[^>]+>", "", tds[0]).strip()
        prior_status = re.sub(r"<[^>]+>", "", tds[-1]).strip()
        prior_status = prior_status if prior_status in STATES else "unverified"
        em = re.search(r'data-evidence="([^"]*)"', row)
        prior_evidence = H.unescape(em.group(1)) if em else f"not checked as of {TODAY}"

        skip = (a.only and cls != a.only) or (a.limit and checked >= a.limit) or not href
        if skip:
            status, evidence = prior_status, prior_evidence
        else:
            resolved_status, resolved_evidence = resolve(href.group(1))
            status, evidence = apply_resolution(
                prior_status, prior_evidence, resolved_status, resolved_evidence, TODAY)
            checked += 1
            print(f"[{i}/{len(rows)}] {status:11} {title[:56]}")
            time.sleep(DELAY)

        if status != prior_status:
            status_changes += 1
        if evidence != prior_evidence:
            evidence_changes += 1
        counts[status] = counts.get(status, 0) + 1
        ledger.append({"title": title, "class": cls,
                       "url": href.group(1) if href else "", "status": status,
                       "evidence": evidence, "checked": str(TODAY) if not skip else None})
        out.append(rewrite_row(row, status, evidence))

    blocked = breaker_tripped(status_changes, len(rows)) and not a.breaker_clearance.strip()
    result = "BLOCKED_CIRCUIT_BREAKER" if blocked else ("DRY_RUN" if a.dry_run else "READY_TO_COMMIT")
    receipt_line = (f"[YouWard] status refresh {TODAY} | {result} | open {counts['open']} / "
                    f"closed {counts['closed']} / upcoming {counts['upcoming']} / "
                    f"unverified {counts['unverified']} | status changes {status_changes}/{len(rows)}")
    receipt = {
        "date": str(TODAY), "result": result, "counts": counts,
        "total": len(rows), "checked": checked,
        "status_changes": status_changes, "evidence_changes": evidence_changes,
        "breaker_ratio": BREAKER_RATIO,
        "breaker_clearance": a.breaker_clearance.strip() or None,
        "receipt_line": receipt_line,
    }

    print("\n=== RECEIPT ===")
    print(receipt_line)
    Path(a.ledger).write_text(json.dumps(ledger, indent=1) + "\n", encoding="utf-8")
    Path(a.receipt).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"ledger -> {a.ledger}")
    print(f"receipt -> {a.receipt}")

    if blocked:
        print("circuit breaker: more than 20% of statuses would change; page not written")
        return BREAKER_EXIT

    new = s[:tb.start(2)] + "\n".join(out) + s[tb.end(2):]
    if len(re.findall(r'<tr\b.*?</tr>', re.search(r'(<tbody>)(.*?)(</tbody>)', new, re.S).group(2), re.S)) != len(rows):
        raise RuntimeError("record count changed during rewrite")
    if a.out:
        Path(a.out).write_text(new, encoding="utf-8")
        print(f"candidate page -> {a.out}")
    else:
        print("no --out: candidate page not written")
    if a.dry_run:
        print("dry run: caller must not commit candidate output")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
