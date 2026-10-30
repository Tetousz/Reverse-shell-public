"""Flask application factory for the web dashboard.

Phase 6c: real API endpoints wired to AppState.
"""

import json
import queue
from pathlib import Path

from flask import (
    Flask, Response, jsonify, request, send_from_directory,
)

from web.stream import get_bus
from web.state import get_state

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    app = Flask(__name__)

    # ---- placeholder UI + health ---------------------------------------

    @app.route("/")
    def index():
        from flask import render_template
        return render_template("index.html")

    @app.route("/health")
    def health():
        return jsonify({
            "status": "ok",
            "version": "0.1.0",
            "subscribers": get_bus().subscriber_count(),
        })

    # ---- SSE ------------------------------------------------------------

    @app.route("/api/logs/stream")
    def logs_stream():
        bus = get_bus()
        q = bus.subscribe()

        def generate():
            try:
                yield f"data: {json.dumps({'type': 'connected', 'ts': 0})}\n\n"
                while True:
                    try:
                        msg = q.get(timeout=15.0)
                        yield f"data: {json.dumps(msg)}\n\n"
                    except queue.Empty:
                        yield ": ping\n\n"
            except GeneratorExit:
                pass
            finally:
                bus.unsubscribe(q)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ---- sessions -------------------------------------------------------

    @app.route("/api/sessions")
    def list_sessions():
        return jsonify(get_state().list_sessions())

    # ---- server ---------------------------------------------------------

    @app.route("/api/server/status")
    def server_status():
        return jsonify(get_state().server_status())

    @app.route("/api/server/toggle", methods=["POST"])
    def toggle_server():
        return jsonify(get_state().toggle_server())

    # ---- command --------------------------------------------------------

    @app.route("/api/command", methods=["POST"])
    def run_command():
        body = request.get_json(silent=True) or {}
        sid = body.get("session_id")
        cmd = body.get("command", "")
        try:
            timeout = float(body.get("timeout", 10.0))
        except (TypeError, ValueError):
            timeout = 10.0

        if sid is None or not cmd:
            return jsonify({"ok": False, "error": "session_id and command required"}), 400
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "session_id must be integer"}), 400

        ok, output = get_state().run_command(sid, cmd, timeout=timeout)
        return jsonify({"ok": ok, "output": output})

    # ---- export + download ---------------------------------------------

    @app.route("/api/formats")
    def list_formats():
        from exporter.export_manager import ExportManager
        return jsonify(ExportManager.formats())

    @app.route("/api/sessions/<int:sid>/revoke", methods=["POST"])
    def revoke_session(sid):
        try:
            result = get_state().revoke_session(sid)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    @app.route("/api/export/<fmt>", methods=["POST"])
    def export(fmt):
        try:
            info = get_state().export(fmt)
            return jsonify({"ok": True, **info})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/download/<name>")
    def download(name):
        builds = _PROJECT_ROOT / "builds"
        target = (builds / name).resolve()
        try:
            target.relative_to(builds)
        except ValueError:
            return jsonify({"error": "invalid path"}), 400
        if not target.is_file():
            return jsonify({"error": "not found"}), 404
        return send_from_directory(str(builds), name, as_attachment=True)

    # ---- debug publish (kept for testing SSE) ---------------------------

    @app.route("/api/_debug/publish")
    def debug_publish():
        bus = get_bus()
        event_type = request.args.get("type", "test")
        msg = request.args.get("msg", "")
        bus.publish(event_type, {"msg": msg})
        return jsonify({"published": True, "subscribers": bus.subscriber_count()})

    return app
