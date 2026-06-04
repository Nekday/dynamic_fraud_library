"""
app.py — Fraud Taxonomy Flask application.

Run (macOS, Postgres.app running):
    cd app
    pip install -r ../requirements.txt
    flask --app app run --debug

Then open http://127.0.0.1:5000

Connection comes from FT_DATABASE_URI (defaults to Postgres.app local).
All database access is in db.py; this file is routing + view logic only.
"""

from flask import Flask, render_template, request, redirect, url_for, flash
import db

app = Flask(__name__)
app.secret_key = "dev-only-change-in-production"  # for flash messages

# STIX vocabulary bridge: shown in the UI beside each object name.
STIX_MAP = {
    "fraud_type": "attack-pattern",
    "signal": "indicator",
    "selector_value": "observed-data",
    "ttp": "attack-pattern / course-of-action",
    "fraudster_profile": "threat-actor / identity",
    "victim_profile": "(custom — not in STIX)",
    "observation": "sighting / observed-data",
    "relationship": "relationship (SRO)",
    "source": "external-reference",
}


@app.context_processor
def inject_globals():
    return {"stix_map": STIX_MAP}


@app.route("/")
def index():
    search = request.args.get("q", "").strip() or None
    ai = request.args.get("ai", "").strip() or None
    types = db.list_fraud_types(search=search, ai_leverage=ai)
    counts = db.staging_counts()
    pending = sum(c["n"] for c in counts if c["status"] == "pending")
    return render_template(
        "index.html",
        fraud_types=types,
        ai_values=db.ai_leverage_values(),
        search=search or "",
        ai_selected=ai or "",
        pending=pending,
    )


@app.route("/fraud-type/<int:fraud_type_id>")
def fraud_type_detail(fraud_type_id):
    ft = db.get_fraud_type(fraud_type_id)
    if not ft:
        flash("Fraud type not found.", "error")
        return redirect(url_for("index"))
    return render_template(
        "fraud_type.html",
        ft=ft,
        tags=db.get_tags_for_type(fraud_type_id),
        ttps=db.get_ttps(fraud_type_id),
        signals=db.get_signals(fraud_type_id),
        selectors=db.get_selectors(fraud_type_id),
        profiles=db.get_profiles(fraud_type_id),
        observations=db.get_observations(fraud_type_id),
    )


@app.route("/signals")
def signals():
    return render_template("signals.html", signals=db.get_signals(None))


@app.route("/selectors")
def selectors():
    return render_template("selectors.html", selectors=db.get_selectors(None))


@app.route("/systems")
def systems():
    return render_template("systems.html", systems=db.external_systems())


# ---- EEI Workbench (Layer 2: read-only display) ----

@app.route("/workbench")
def workbench():
    return render_template("workbench_list.html", cases=db.list_cases())


@app.route("/workbench/<int:observation_id>")
def workbench_case(observation_id):
    case = db.get_case(observation_id)
    if not case:
        flash("Case not found.", "error")
        return redirect(url_for("workbench"))
    eeis = db.get_eei_candidates(observation_id)
    segments = _segment_text(case["captured_text"], eeis)
    return render_template("workbench_case.html", case=case, eeis=eeis, segments=segments)


@app.route("/workbench/<int:observation_id>/submit", methods=["POST"])
def workbench_submit(observation_id):
    """
    Receive staged review decisions as a batch (R1). The form sends, for each
    EEI the reviewer touched, a field decision_<eei_id> = approved|rejected|pending.
    Untouched EEIs are not submitted and keep their current status.
    """
    decisions = {}
    for key, val in request.form.items():
        if key.startswith("decision_") and val in ("approved", "rejected", "pending"):
            try:
                eei_id = int(key[len("decision_"):])
            except ValueError:
                continue
            decisions[eei_id] = val
    if not decisions:
        flash("No decisions to submit.", "info")
        return redirect(url_for("workbench_case", observation_id=observation_id))
    s = db.apply_eei_decisions(observation_id, decisions)
    flash(
        f"Saved: {s['approved']} approved, {s['rejected']} rejected, "
        f"{s['reset']} reset to pending. {s['promoted']} new selector(s) promoted.",
        "success",
    )
    return redirect(url_for("workbench_case", observation_id=observation_id))


def _segment_text(text, eeis):
    """
    Split captured text into an ordered list of segments for safe rendering.
    Each segment is either plain text or a highlighted EEI span. Doing this in
    Python (not Jinja) keeps offset handling reliable. Overlapping/duplicate
    offsets are skipped defensively so the text is never corrupted.
    """
    if not text:
        return []
    # collect valid, non-overlapping spans sorted by start
    spans = []
    last_end = 0
    valid = sorted(
        [e for e in eeis if e["start_offset"] is not None and e["end_offset"] is not None
         and 0 <= e["start_offset"] < e["end_offset"] <= len(text)],
        key=lambda e: e["start_offset"],
    )
    segments = []
    cursor = 0
    for e in valid:
        s, en = e["start_offset"], e["end_offset"]
        if s < cursor:
            continue  # overlaps a prior span; skip defensively
        if s > cursor:
            segments.append({"kind": "text", "text": text[cursor:s]})
        segments.append({
            "kind": "eei",
            "text": text[s:en],
            "eei_id": e["eei_id"],
            "classifier_type": e["classifier_type"],
            "status": e["status"],
        })
        cursor = en
    if cursor < len(text):
        segments.append({"kind": "text", "text": text[cursor:]})
    return segments


# ---- Two-lane staging review ----

@app.route("/review")
def review():
    lane = request.args.get("lane", "single")
    if lane not in ("single", "bulk"):
        lane = "single"

    batches = None
    entries = None
    expanded = request.args.get("expand", "").strip() or None  # provenance to show in full

    if lane == "bulk":
        SAMPLE_SIZE = 3
        batches = []
        for b in db.bulk_batches(status="pending"):
            prov = b["provenance"]
            show_all = (expanded == prov)
            rows = db.bulk_batch_entries(
                prov, status="pending",
                limit=None if show_all else SAMPLE_SIZE,
            )
            batches.append({
                "provenance": prov,
                "n": b["n"],
                "source_url": b["source_url"],
                "source_name": b["source_name"],
                "first_scraped": b["first_scraped"],
                "last_scraped": b["last_scraped"],
                "rows": rows,
                "showing_all": show_all,
                "sample_size": SAMPLE_SIZE,
                "has_more": (b["n"] > SAMPLE_SIZE) and not show_all,
            })
    else:
        entries = db.list_staging(status="pending", lane="single")

    return render_template(
        "review.html",
        lane=lane,
        entries=entries,
        batches=batches,
        counts=db.staging_counts(),
    )


@app.route("/review/<int:staging_id>/<action>", methods=["POST"])
def review_action(staging_id, action):
    if action not in ("approve", "reject"):
        flash("Unknown action.", "error")
        return redirect(url_for("review"))
    note = request.form.get("note", "").strip() or None
    status = "approved" if action == "approve" else "rejected"
    db.update_staging_status(staging_id, status, note)
    flash(f"Entry #{staging_id} {status}.", "success")
    return redirect(url_for("review", lane="single"))


@app.route("/review/bulk/<action>", methods=["POST"])
def review_bulk(action):
    if action not in ("approve", "reject"):
        flash("Unknown action.", "error")
        return redirect(url_for("review", lane="bulk"))
    provenance = request.form.get("provenance", "").strip()
    note = request.form.get("note", "").strip() or None
    if not provenance:
        flash("No provenance specified for bulk action.", "error")
        return redirect(url_for("review", lane="bulk"))
    status = "approved" if action == "approve" else "rejected"
    db.bulk_update_status(provenance, status, note)
    flash(f"Bulk {status} for provenance '{provenance}'.", "success")
    return redirect(url_for("review", lane="bulk"))


if __name__ == "__main__":
    app.run(debug=True)
