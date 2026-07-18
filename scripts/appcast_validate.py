#!/usr/bin/env python3
"""appcast_validate.py — canonical Sparkle appcast.xml validator (CPM-153 R1).

stdlib-only (python3, no pip installs — this runs on a bare ubuntu-latest
runner as well as the macOS dev/CI host). Validates the structural and
ordering invariants that scripts/lib/appcast.sh's helpers already enforce
at cut time (appcast_splice_item / appcast_retag_item), so the same rules
can be re-checked wherever the appcast actually lands: this monorepo's
docs/appcast.xml today, and the mirrored copy's PR gate in the public
CookPlanStudio-releases repo (see appcast-validate.yml, CPM-153 T3).

Usage:
    appcast_validate.py <path>
    appcast_validate.py <path> --assets <owner/repo>
    appcast_validate.py <path> --assets-plan <owner/repo>

Modes:
    (default)      Structural checks only: well-formed XML, per-item
                    required elements, sparkle:version strictly decreasing
                    in document order (gaps legal), sparkle:channel
                    vocabulary (dev/test only; stable = untagged).
    --assets       Additionally maps every enclosure URL to a real,
                    non-draft GitHub release asset of <owner/repo> whose
                    size matches the enclosure's length= attribute. Calls
                    the GitHub REST API via urllib (stdlib only); reads
                    GITHUB_TOKEN from the environment if present.
                    NETWORK — never used by the local test harness.
    --assets-plan  Prints the exact per-item lookups --assets would
                    perform, one per line, in document order, WITHOUT
                    making any network call:
                        <tag>\\t<asset-filename>\\t<expected-length>
                    This is the test seam for --assets (spec R1) — the
                    harness pins this output exactly. Live --assets
                    behavior is exercised for real only by the
                    releases-repo workflow's introducing PR (CPM-153 T3).

Output contract: plan-tuple lines and violation lines never mix. The
offline validations run first in every mode; if any violation exists,
stdout carries ONLY the "RULE: message" lines (exit 1) — --assets-plan
prints zero plan lines, and --assets performs zero network lookups.

Exit codes:
    0   clean — no violations.
    1   one or more violations, each printed to stdout as "RULE: message"
        (one per line). RULE is one of: xml, structure, monotonic,
        channel, assets.
    2   usage error (bad/missing arguments) or IO error (missing/unreadable
        input file).

All violations are collected and printed together (not fail-fast on the
first one) so a single run surfaces everything a caller needs to fix —
matching the way scripts/lib/appcast.sh's own callers expect one pass to
be enough.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
NS = {"sparkle": SPARKLE_NS}

# GitHub release tag URLs look like:
#   https://github.com/<owner>/<repo>/releases/tag/<tag>
# appcast_splice_item (scripts/lib/appcast.sh) writes exactly this shape into
# each item's <link>.
_TAG_RE = re.compile(r"/releases/tag/([^/]+)/?$")

# sparkle:version must be a positive integer with no leading zero — matches
# how CFBundleVersion / CURRENT_PROJECT_VERSION is always emitted by the
# release tooling; a leading-zero or non-digit string is never legitimate.
_POSITIVE_INT_RE = re.compile(r"[1-9][0-9]*")


def _usage_error(message):
    print(f"usage error: {message}", file=sys.stderr)
    print(
        "usage: appcast_validate.py <path> [--assets <owner/repo> | --assets-plan <owner/repo>]",
        file=sys.stderr,
    )
    return 2


def _io_error(message):
    print(f"error: {message}", file=sys.stderr)
    return 2


def parse_args(argv):
    """Parses argv into (path, mode, owner_repo).

    mode is None, "assets", or "assets-plan"; owner_repo is None unless
    mode is set. Raises ValueError(message) on any usage problem.
    """
    mode = None
    owner_repo = None
    positional = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--assets", "--assets-plan"):
            if mode is not None:
                raise ValueError("--assets and --assets-plan are mutually exclusive")
            if i + 1 >= len(argv):
                raise ValueError(f"{arg} requires an <owner/repo> argument")
            mode = "assets" if arg == "--assets" else "assets-plan"
            owner_repo = argv[i + 1]
            i += 2
            continue
        positional.append(arg)
        i += 1

    if len(positional) != 1:
        raise ValueError(
            f"expected exactly one <path> argument, got {len(positional)}"
        )

    if mode is not None and "/" not in owner_repo:
        raise ValueError(
            f"<owner/repo> must look like 'owner/repo', got {owner_repo!r}"
        )

    return positional[0], mode, owner_repo


def _item_label(item, idx):
    title_el = item.find("title")
    if title_el is not None and title_el.text and title_el.text.strip():
        return f"item {idx} ({title_el.text.strip()})"
    return f"item {idx}"


def validate(path):
    """Runs the structural/monotonic/channel checks (spec R1, minus
    --assets). Returns (violations, root): root is the parsed Element on
    success, or None if the file wasn't well-formed XML.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return [f"xml: {path} is not well-formed XML — {exc}"], None

    root = tree.getroot()
    violations = []

    channel = root.find("channel")
    if channel is None:
        violations.append("structure: no <channel> element found")
        return violations, root

    items = channel.findall("item")
    versions = []  # list of (idx, version_int, label), document order

    for idx, item in enumerate(items, start=1):
        label = _item_label(item, idx)

        version_el = item.find("sparkle:version", NS)
        if version_el is None or not (version_el.text or "").strip():
            violations.append(f"structure: {label} missing <sparkle:version>")
        else:
            vtext = version_el.text.strip()
            if _POSITIVE_INT_RE.fullmatch(vtext):
                versions.append((idx, int(vtext), label))
            else:
                violations.append(
                    f"structure: {label} sparkle:version {vtext!r} is not a "
                    "positive integer"
                )

        channel_el = item.find("sparkle:channel", NS)
        if channel_el is not None:
            raw = channel_el.text or ""
            ctext = raw.strip()
            if raw != ctext:
                # Sparkle does NOT strip channel text (#1041 F1): 'dev ' is a
                # distinct channel, so dev clients would silently never see
                # the item — exactly the invisibility class this validator
                # exists to catch.
                violations.append(
                    f"channel: {label} sparkle:channel {raw!r} has "
                    "leading/trailing whitespace — Sparkle does not strip, "
                    "so this is a distinct channel, never matching "
                    "'dev'/'test'"
                )
            elif ctext not in ("dev", "test"):
                violations.append(
                    f"channel: {label} sparkle:channel {ctext!r} must be "
                    "'dev' or 'test' (omit the element entirely for stable)"
                )

        enclosure = item.find("enclosure")
        if enclosure is None:
            violations.append(f"structure: {label} missing <enclosure> element")
        else:
            if not (enclosure.get("url") or "").strip():
                violations.append(
                    f"structure: {label} <enclosure> missing url= attribute"
                )
            ed_sig = enclosure.get(f"{{{SPARKLE_NS}}}edSignature")
            if not (ed_sig or "").strip():
                violations.append(
                    f"structure: {label} <enclosure> missing non-empty "
                    "sparkle:edSignature= attribute"
                )
            length = enclosure.get("length")
            if not length or not length.isdigit():
                violations.append(
                    f"structure: {label} <enclosure> missing or non-numeric "
                    "length= attribute"
                )
            # Required per CPM-153 spec §2-E (#1041 F3): presence + non-empty
            # only — no specific MIME value is pinned. appcast_splice_item
            # always emits type="application/x-apple-diskimage"; this catches
            # hand-edits to the public repo that drop the attribute.
            if not (enclosure.get("type") or "").strip():
                violations.append(
                    f"structure: {label} <enclosure> missing non-empty "
                    "type= attribute"
                )

    # Monotonicity: sparkle:version strictly decreasing across ALL items in
    # document order (checking adjacent pairs is sufficient — a sequence is
    # strictly decreasing overall iff every adjacent pair is). Gaps are
    # legal (e.g. 70, 69, 67 — 68 is a legitimate hole from a clean revert);
    # this only rejects "not less than the previous" at some adjacent pair,
    # which catches both the s102 dup-CPV class (equal) and a misordered
    # splice (increasing).
    for prev, cur in zip(versions, versions[1:]):
        _, prev_v, prev_label = prev
        _, cur_v, cur_label = cur
        if not (cur_v < prev_v):
            violations.append(
                f"monotonic: {cur_label} sparkle:version {cur_v} is not less "
                f"than the preceding {prev_label} sparkle:version {prev_v} "
                "(document order requires strictly decreasing versions)"
            )

    return violations, root


def _asset_lookup_for_item(item, idx, label, violations):
    """Resolves one item's (tag, filename, expected length) for the assets
    lookup, or returns None (appending an 'assets:' violation) if the item
    doesn't carry enough info to resolve one. Missing enclosure/url/length
    are already reported as 'structure:' violations by validate() — this
    only covers the assets-mode-specific tag-resolution failure.
    """
    link_el = item.find("link")
    link = (link_el.text or "").strip() if link_el is not None else ""
    enclosure = item.find("enclosure")
    url = (enclosure.get("url") or "").strip() if enclosure is not None else ""
    length = enclosure.get("length") if enclosure is not None else None

    if not link or not url or not length:
        return None

    match = _TAG_RE.search(link)
    if not match:
        violations.append(
            f"assets: {label} <link> {link!r} does not look like a GitHub "
            "release tag URL (expected .../releases/tag/<tag>) — cannot "
            "resolve an asset lookup"
        )
        return None

    tag = match.group(1)
    filename = url.rsplit("/", 1)[-1]
    return tag, filename, length


def build_asset_plan(root, violations):
    """Returns the ordered list of (tag, filename, length) tuples — the
    exact lookups --assets would perform, one per item, document order.
    """
    channel = root.find("channel")
    if channel is None:
        return []

    plan = []
    for idx, item in enumerate(channel.findall("item"), start=1):
        label = _item_label(item, idx)
        lookup = _asset_lookup_for_item(item, idx, label, violations)
        if lookup is not None:
            plan.append(lookup)
    return plan


def fetch_release_by_tag(owner_repo, tag, token):
    owner, repo = owner_repo.split("/", 1)
    encoded_tag = urllib.parse.quote(tag, safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{encoded_tag}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cookplanmobile-appcast-validate",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def run_assets_check(owner_repo, plan, violations):
    """NETWORK. Confirms every planned lookup resolves to a non-draft
    release asset of the right size. Never called by the local test
    harness — inspection-only until CPM-153 T3's workflow run.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    for tag, filename, length in plan:
        try:
            release = fetch_release_by_tag(owner_repo, tag, token)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                violations.append(
                    f"assets: release tag {tag!r} not found in {owner_repo}"
                )
            else:
                violations.append(
                    f"assets: failed to query {owner_repo} release {tag!r} "
                    f"— HTTP {exc.code}"
                )
            continue
        except urllib.error.URLError as exc:
            violations.append(
                f"assets: failed to query {owner_repo} release {tag!r} — "
                f"{exc.reason}"
            )
            continue

        if release.get("draft"):
            violations.append(
                f"assets: release {tag!r} in {owner_repo} is a draft"
            )
            continue

        assets = release.get("assets") or []
        matching = next((a for a in assets if a.get("name") == filename), None)
        if matching is None:
            violations.append(
                f"assets: no asset named {filename!r} on release {tag!r} "
                f"in {owner_repo}"
            )
            continue

        actual_size = matching.get("size")
        expected_size = int(length)
        if actual_size != expected_size:
            violations.append(
                f"assets: asset {filename!r} on release {tag!r} in "
                f"{owner_repo} has size {actual_size} but appcast length= "
                f"says {expected_size}"
            )


def main(argv):
    try:
        path, mode, owner_repo = parse_args(argv)
    except ValueError as exc:
        return _usage_error(str(exc))

    if not os.path.isfile(path):
        return _io_error(f"{path}: no such file")
    try:
        with open(path, "rb"):
            pass
    except OSError as exc:
        return _io_error(f"{path}: {exc}")

    violations, root = validate(path)

    # Output contract: violations and plan-tuple lines are mutually
    # exclusive on stdout. The offline validations (plus assets-plan tag
    # resolution) run FIRST; any violation means ONLY "RULE: message" lines
    # are printed (exit 1) — never a mix of plan lines and violations.
    # Symmetrically, --assets performs ZERO network lookups when the
    # offline pass already failed, so --assets-plan stays an exact seam:
    # the lookups it prints are precisely the ones --assets would perform.
    plan = []
    if root is not None and mode is not None:
        plan = build_asset_plan(root, violations)

    if violations:
        for violation in violations:
            print(violation)
        return 1

    if mode == "assets-plan":
        for tag, filename, length in plan:
            print(f"{tag}\t{filename}\t{length}")
    elif mode == "assets":
        run_assets_check(owner_repo, plan, violations)
        if violations:
            for violation in violations:
                print(violation)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
