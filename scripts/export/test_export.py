"""Integration check: temporary fixture only; never opens the user's database.

Run: python scripts/export/test_export.py
Requires Java 17+, PowerShell and the cached dependencies used by the exporter.
"""
import hashlib
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="material-export-test-") as temporary:
        work = Path(temporary)
        database = work / "fixture.db"
        connection = sqlite3.connect(database)
        schema = (root / "backend/src/main/resources/sql/material.sql").read_text(encoding="utf-8")
        connection.executescript(schema)
        connection.execute(
            "INSERT INTO material(id,category,title,attributes,tags,source,profile,create_time,update_time) "
            "VALUES(1,?,?,?,?,?,?,?,?)",
            ("world", "中文\n册封", json.dumps({"代价": ["效忠"]}, ensure_ascii=False),
             '["骑士"]', '{"type":"merge","members":[2]}', '{"tier":1}', "2026-01-01", "2026-01-01"),
        )
        connection.execute(
            "INSERT INTO material(id,category,title,merged_into,create_time,update_time) "
            "VALUES(2,'world','成员',1,'2026-01-01','2026-01-01')"
        )
        connection.commit()
        connection.close()
        before = hashlib.sha256(database.read_bytes()).hexdigest()

        def run(output):
            return subprocess.run(
                ["pwsh.exe", "-NoProfile", "-File", str(root / "scripts/export/export-materials.ps1"),
                 "-Database", str(database), "-OutputDirectory", str(output)],
                capture_output=True, check=False,
            )

        output = work / "snapshot"
        result = run(output)
        if result.returncode:
            raise AssertionError(result.stderr.decode(errors="replace"))
        payload = (output / "materials.jsonl").read_bytes()
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert len(rows) == 2 and manifest["records"] == 2
        assert manifest["retrievalEligible"] == 1
        assert rows[0]["title"] == "中文\n册封"
        assert rows[0]["attributes"] == {"代价": ["效忠"]}
        assert rows[0]["source"]["members"] == [2]
        assert rows[1]["mergedInto"] == 1 and not rows[1]["retrievalEligible"]
        assert rows[1]["attributes"] is None
        assert not payload.startswith(b"\xef\xbb\xbf")
        assert manifest["sha256"] == hashlib.sha256(payload).hexdigest()
        assert hashlib.sha256(database.read_bytes()).hexdigest() == before
        assert run(output).returncode != 0  # Existing exports cannot be overwritten.
        assert (output / "materials.jsonl").read_bytes() == payload

        connection = sqlite3.connect(database)
        connection.execute("UPDATE material SET attributes='broken-json' WHERE id=1")
        connection.commit()
        connection.close()
        broken = work / "broken"
        assert run(broken).returncode != 0
        assert not (broken / "manifest.json").exists()
        assert not (broken / "materials.jsonl").exists()
    print("PASS: UTF-8, JSON fields, merge links, counts/hash, read-only, overwrite guard, invalid JSON rejection")


if __name__ == "__main__":
    main()
