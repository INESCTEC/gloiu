#!/usr/bin/env python3
import argparse, json, sys, requests, datetime, pathlib

def main():
    ap = argparse.ArgumentParser(
        description="Fetch persona report text and (optionally) synthesize audio via /persona_report_audio."
    )
    ap.add_argument("schedule_json", help="Path to optimized schedule JSON")
    ap.add_argument("--url", default="http://localhost:8000/persona_report",
                    help="API URL for persona_report (text endpoint)")
    ap.add_argument("--persona", default=None, help='e.g., "Homer Simpson" (optional)')
    ap.add_argument("--out-md", default=None, help="Save Markdown to this path")
    ap.add_argument("--out-json", default=None, help="Save raw JSON to this path")
    ap.add_argument("--audio", default=None,
                    help="Save spoken persona report to this MP3 file (calls /persona_report_audio)")
    ap.add_argument("--timeout", type=int, default=300, help="HTTP timeout seconds")
    args = ap.parse_args()

    # read schedule payload
    try:
        payload = json.loads(pathlib.Path(args.schedule_json).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERR] failed to read schedule: {e}", file=sys.stderr)
        sys.exit(2)

    # call /persona_report (text)
    text_url = args.url if not args.persona else f"{args.url}?persona={requests.utils.quote(args.persona)}"
    try:
        r = requests.post(text_url, json=payload, timeout=args.timeout)
    except Exception as e:
        print(f"[ERR] request to persona_report failed: {e}", file=sys.stderr); sys.exit(3)

    print("HTTP", r.status_code)
    if not r.ok:
        print(r.text); sys.exit(1)

    try:
        data = r.json()
    except Exception:
        print("[ERR] non-JSON response from persona_report:\n", r.text[:4000], file=sys.stderr)
        sys.exit(4)

    persona = data.get("persona", "<unknown>")
    text = data.get("text", "")

    print("\n=== Persona ===")
    print(persona)
    print("\n=== Report ===")
    print(text)

    # optional: save markdown / raw json
    if args.out_md:
        md = f"# Persona: {persona}\n\n{text}\n"
        p = pathlib.Path(args.out_md); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(md, encoding="utf-8")
        print(f"\n[ok] saved markdown -> {p}")

    if args.out_json:
        p = pathlib.Path(args.out_json); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] saved json -> {p}")

    # optional: synthesize audio via /persona_report_audio (server returns MP3)
    if args.audio:
        base = args.url.split("/persona_report")[0].rstrip("/")  # e.g., http://localhost:8000
        audio_url = f"{base}/persona_report_audio"
        if args.persona:
            audio_url += f"?persona={requests.utils.quote(args.persona)}"
        try:
            ar = requests.post(audio_url, json=payload, timeout=args.timeout)
        except Exception as e:
            print(f"[ERR] request to persona_report_audio failed: {e}", file=sys.stderr); sys.exit(5)

        if ar.status_code != 200:
            print(f"[ERR] TTS API returned {ar.status_code}")
            print(ar.text); sys.exit(6)

        # save bytes (MP3)
        out_path = pathlib.Path(args.audio)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(ar.content)
        print(f"[ok] Saved audio to {out_path}")

if __name__ == "__main__":
    main()
