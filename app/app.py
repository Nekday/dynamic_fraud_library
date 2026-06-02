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
