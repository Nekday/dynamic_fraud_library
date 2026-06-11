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
    # `pending` drives the nav badge (Workbench parent + Intake Gate child) on
    # EVERY page, so it's computed here rather than per-route. Previously only
    # the index route passed it, so the badge was stale/absent elsewhere.
    counts = db.staging_counts()
    pending = sum(c["n"] for c in counts if c["status"] == "pending")
    return {"stix_map": STIX_MAP, "pending": pending}


@app.route("/")
def index():
    search = request.args.get("q", "").strip() or None
    ai = request.args.get("ai", "").strip() or None
    types = db.list_fraud_types(search=search, ai_leverage=ai)
    return render_template(
        "index.html",
        fraud_types=types,
        ai_values=db.ai_leverage_values(),
        search=search or "",
        ai_selected=ai or "",
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

@app.route("/fraud-types")
def fraud_types():
    return render_template("fraud_types.html", tree=db.list_fraud_type_tree())


@app.route("/fraud-types/add", methods=["POST"])
def fraud_types_add():
    name = request.form.get("name", "")
    parent_raw = request.form.get("parent_id", "")
    parent_id = int(parent_raw) if parent_raw.strip().isdigit() else None
    new_id = db.add_fraud_type(name, parent_id=parent_id)
    if new_id:
        flash(f"Added fraud type “{name.strip()}”.", "success")
    else:
        flash("Could not add (empty or duplicate name).", "error")
    return redirect(url_for("fraud_types"))


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
    clippings = db.get_note_clippings(observation_id)
    tree = db.list_fraud_type_tree()
    linked = db.get_case_fraud_types(observation_id)
    linked_ids = [t["fraud_type_id"] for t in linked]
    promotable = db.get_promotable_eeis(observation_id)
    return render_template("workbench_case.html", case=case, eeis=eeis,
                           segments=segments, clippings=clippings,
                           tree=tree, linked=linked, linked_ids=linked_ids,
                           promotable=promotable)


@app.route("/workbench/<int:observation_id>/link-types", methods=["POST"])
def workbench_link_types(observation_id):
    ids = []
    for v in request.form.getlist("fraud_type_ids"):
        if v.strip().isdigit():
            ids.append(int(v))
    db.set_case_fraud_types(observation_id, ids)
    flash(f"Linked {len(ids)} fraud type(s) to this case.", "success")
    return redirect(url_for("workbench_case", observation_id=observation_id))


@app.route("/workbench/<int:observation_id>/promote", methods=["POST"])
def workbench_promote(observation_id):
    eei_ids = []
    for v in request.form.getlist("promote_eei"):
        if v.strip().isdigit():
            eei_ids.append(int(v))
    if not eei_ids:
        flash("No EEIs selected to promote.", "info")
        return redirect(url_for("workbench_case", observation_id=observation_id))
    s = db.promote_eeis_to_library(observation_id, eei_ids)
    if s["skipped_no_types"]:
        flash("Link the case to at least one fraud type before promoting.", "error")
    else:
        flash(f"Promoted to library: {s['signals']} signal(s), {s['ttps']} TTP(s).", "success")
    return redirect(url_for("workbench_case", observation_id=observation_id))


@app.route("/workbench/<int:observation_id>/note", methods=["POST"])
def workbench_save_note(observation_id):
    db.save_analyst_note(observation_id, request.form.get("analyst_note", ""))
    flash("Case notes saved.", "success")
    return redirect(url_for("workbench_case", observation_id=observation_id))


@app.route("/workbench/<int:observation_id>/clip/<int:eei_id>/remove", methods=["POST"])
def workbench_remove_clip(observation_id, eei_id):
    db.remove_eei(eei_id)
    flash("Clipping removed.", "success")
    return redirect(url_for("workbench_case", observation_id=observation_id))


@app.route("/workbench/<int:observation_id>/tag", methods=["POST"])
def workbench_tag(observation_id):
    """
    Receive a human highlight-and-assign (3b). Expects:
      highlight_text, start_offset, end_offset, types (comma-separated).
    Creates one approved human-origin EEI per chosen type. Returns JSON so the
    page can update without a full reload.
    """
    from flask import jsonify
    text = request.form.get("highlight_text", "")
    types = [t for t in (request.form.get("types", "").split(",")) if t]
    try:
        start = int(request.form.get("start_offset", ""))
        end = int(request.form.get("end_offset", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "Bad offsets."}), 400
    try:
        new_ids = db.add_human_eeis(observation_id, text, start, end, types)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "new_ids": new_ids, "count": len(new_ids)})


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
