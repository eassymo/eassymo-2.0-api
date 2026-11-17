"""Upload frame screenshots made by the client capture script (`npm run capture:frames`).

Only codes listed as captured in the latest capture-report.json are uploaded, so PNGs left over
from earlier runs are never re-published as new. Each `<code>.png` / `<code>.jpg` under the folder (any depth) goes to S3 `frames/<code>/<timestamp>.<ext>` and the frame gets
`screenshot_url`, `screenshot_source="script"` and `captured_at`. Files whose code is not a
known frame are skipped and reported.
Usage: python -m scripts.upload_frame_screenshots ../eassymo-2.0-client/cypress/screenshots
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _captured_in_report(folder: Path):
    """Codes the last capture run actually shot (capture-report.json), or None without a report."""
    reports = sorted(Path(folder).rglob("capture-report.json"), key=lambda p: p.stat().st_mtime)
    if not reports:
        return None
    return set(json.loads(reports[-1].read_text(encoding="utf-8")).get("captured", []))


def run(folder: Path, db, bucket, bucket_name: str) -> dict:
    known = {f["code"] for f in db["frames"].find({}, {"code": 1})}
    captured = _captured_in_report(folder)
    uploaded, skipped, not_in_report = [], [], []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    images = [p for p in Path(folder).rglob("*") if p.suffix.lower() in CONTENT_TYPES]  # Cypress nests under the spec name
    for png in sorted(images):
        code = png.stem
        if code not in known:
            skipped.append(code)
            continue
        if captured is not None and code not in captured:
            not_in_report.append(code)  # PNG left over from an earlier run
            continue
        suffix = png.suffix.lower()
        key = f"frames/{code}/{stamp}{suffix}"
        bucket.upload_file(str(png), key, ExtraArgs={"ContentType": CONTENT_TYPES[suffix]})
        db["frames"].update_one({"code": code}, {"$set": {
            "screenshot_url": f"https://{bucket_name}.s3.amazonaws.com/{key}",
            "screenshot_source": "script",
            "captured_at": datetime.now(timezone.utc),
            "captured_by": "capture-script",
            "needs_update": False,
        }})
        uploaded.append(code)
    result = {"uploaded": uploaded, "skipped": skipped}
    if not_in_report:
        result["not_in_report"] = not_in_report
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    from app.config import database
    from app.factories.AwsFactory import create_aws_session

    bucket_name = os.getenv("AWS_BUCKET_NAME")
    bucket = create_aws_session().resource("s3").Bucket(bucket_name)
    result = run(args.folder, database.db, bucket, bucket_name)
    print(f"uploaded {len(result['uploaded'])}: {', '.join(result['uploaded'])}")
    if result.get("not_in_report"):
        print(f"not captured in the last run (left untouched) {len(result['not_in_report'])}: {', '.join(result['not_in_report'])}")
    if result["skipped"]:
        print(f"skipped (unknown code) {len(result['skipped'])}: {', '.join(result['skipped'])}")


if __name__ == "__main__":
    main()
