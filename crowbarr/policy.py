"""Bounded policy projections. catalog.decision remains the policy oracle."""
from __future__ import annotations

import json
import time

from .catalog import decision, file_targets, identity

BATCH_SIZE = 200


def migrate(connection):
    """Called inside Database's migration transaction; never commits independently."""
    if connection.execute("SELECT 1 FROM meta WHERE key='policy_projection_v1'").fetchone():
        return
    columns = {r[1] for r in connection.execute("PRAGMA table_info(jobs)")}
    for name in ("policy_revision", "policy_input_revision"):
        if name not in columns:
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} INTEGER NOT NULL DEFAULT -1")
    connection.execute("CREATE TABLE policy_inputs (path TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
    connection.execute("CREATE TABLE policy_dirty (path TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
    connection.execute("CREATE TABLE policy_scan (id INTEGER PRIMARY KEY CHECK(id=1), "
                       "cursor INTEGER NOT NULL, end_id INTEGER NOT NULL, pending INTEGER NOT NULL)")
    connection.execute("INSERT INTO policy_scan SELECT 1,0,COALESCE(MAX(id),0),1 FROM jobs")
    connection.execute("INSERT INTO meta VALUES ('policy_revision','0')")
    connection.execute("CREATE INDEX IF NOT EXISTS managed_item ON managed_media(provider,item_id,path)")
    for table, column in (("managed_media", "path"), ("library_metadata", "path"),
                          ("audio_metadata", "path"), ("jobs", "media")):
        events = ("INSERT", "DELETE", f"UPDATE OF {column}") if table == "jobs" else (
            "INSERT", "UPDATE", "DELETE")
        for event in events:
            references = [f"OLD.{column}"] if event == "DELETE" else [f"NEW.{column}"]
            if event.startswith("UPDATE"):
                references.insert(0, f"OLD.{column}")
            statements = " ".join(dirty_sql(path) for path in references)
            name = f"policy_{table}_{event.split()[0].lower()}"
            connection.execute(f"CREATE TRIGGER {name} AFTER {event} ON {table} BEGIN {statements} END")
    for event in ("INSERT", "UPDATE", "DELETE"):
        connection.execute(f"CREATE TRIGGER policy_rules_{event.lower()} AFTER {event} "
                           f"ON library_rules BEGIN {global_sql()} END")
        ref = "OLD" if event == "DELETE" else "NEW"
        connection.execute(f"CREATE TRIGGER policy_audio_rule_{event.lower()} AFTER {event} ON meta "
                           f"WHEN {ref}.key='skip_other_audio' BEGIN {global_sql()} END")
    connection.execute("INSERT INTO meta VALUES ('policy_projection_v1','1')")


def dirty_sql(path):
    # path is a trigger OLD/NEW expression, never caller-provided SQL.
    return (
        f"INSERT INTO policy_inputs VALUES ({path},1) ON CONFLICT(path) DO UPDATE "
        "SET revision=revision+1; "
        "INSERT INTO policy_dirty SELECT path,revision FROM policy_inputs "
        f"WHERE path={path} AND EXISTS (SELECT 1 FROM jobs WHERE media={path}) "
        "ON CONFLICT(path) DO UPDATE SET revision=excluded.revision;"
    )


def global_sql():
    return (
        "UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='policy_revision'; "
        "UPDATE policy_scan SET cursor=0,end_id=(SELECT COALESCE(MAX(id),0) FROM jobs),pending=1 WHERE id=1;"
    )


def revision(connection):
    return int(connection.execute("SELECT value FROM meta WHERE key='policy_revision'").fetchone()[0])


def mark_dirty(connection, paths=None):
    if paths is None:
        connection.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='policy_revision'")
        connection.execute("UPDATE policy_scan SET cursor=0,end_id=(SELECT COALESCE(MAX(id),0) "
                           "FROM jobs),pending=1 WHERE id=1")
    else:
        for path in dict.fromkeys(paths):
            connection.execute("INSERT INTO policy_inputs VALUES (?,1) ON CONFLICT(path) "
                               "DO UPDATE SET revision=revision+1", (path,))
            connection.execute("INSERT INTO policy_dirty SELECT path,revision FROM policy_inputs "
                               "WHERE path=? AND EXISTS (SELECT 1 FROM jobs WHERE media=?) "
                               "ON CONFLICT(path) DO UPDATE SET revision=excluded.revision", (path, path))
    return revision(connection)


def record(connection, media):
    """Same identity/metadata/audio precedence as catalog.rows, for exactly one path."""
    row = connection.execute("SELECT * FROM managed_media INDEXED BY managed_path "
                             "WHERE path=? ORDER BY provider,file_id LIMIT 1", (media,)).fetchone()
    saved = connection.execute("SELECT metadata FROM library_metadata WHERE path=?", (media,)).fetchone()
    # Orphan metadata must not leak a removed manager's identity into folder mode.
    data = {**dict(row), **json.loads(saved[0] or "{}")} if row and saved else (
        dict(row) if row else {"path": media, "provider": "folders"})
    result = identity(data)
    audio = connection.execute("SELECT languages FROM audio_metadata WHERE path=?", (media,)).fetchone()
    if audio:
        result["audio_languages"] = json.loads(audio[0])
    return result


def decide(connection, item):
    targets = [("file", target) for target in file_targets(item)]
    targets += [("title", item["key"])]
    if item["season"] is not None:
        targets.append(("season", f"{item['key']}:{item['season']}"))
    rules = {}
    for scope, target in targets:
        row = connection.execute("SELECT decision FROM library_rules WHERE scope=? AND target=?",
                                 (scope, target)).fetchone()
        if row:
            rules[scope, target] = row[0]
    auto = connection.execute("SELECT value FROM meta WHERE key='skip_other_audio'").fetchone()
    return decision(item, rules, auto is None or auto[0] == "true")


def project(connection, item, result, rule_revision=None, input_revision=None):
    media = item["path"]
    if rule_revision is None:
        rule_revision = revision(connection)
    if input_revision is None:
        row = connection.execute("SELECT revision FROM policy_inputs WHERE path=?", (media,)).fetchone()
        input_revision = row[0] if row else 0
    order = (f"{item['title'].casefold()}|{item['key']}|{item['season'] or 0:04}|"
             f"{min(item['episodes'] or [0]):05}|{media}")
    blocked = result["reason"] if result["skipped"] else ""
    connection.execute("UPDATE jobs SET library_order=?,library_blocked=?,policy_revision=?,"
                       "policy_input_revision=? WHERE media=?", (order, blocked, rule_revision, input_revision, media))
    if result["skipped"]:
        connection.execute("UPDATE jobs SET state='skipped',stage='Library preference',error=? "
                           "WHERE media=? AND state IN ('queued','waiting','retry')", (blocked, media))
        connection.execute("UPDATE jobs SET cancel_requested=1 WHERE media=? AND state='processing'", (media,))
    else:
        connection.execute("UPDATE jobs SET state=CASE WHEN ready>? THEN 'waiting' ELSE 'queued' END,"
                           "stage='',error=NULL,cancel_requested=0,attempts=0 "
                           "WHERE media=? AND state='skipped' AND stage='Library preference'", (time.time(), media))
    connection.execute("DELETE FROM policy_dirty WHERE path=? AND revision=?", (media, input_revision))


def check(connection, media, apply=False):
    item = record(connection, media)
    result = decide(connection, item)
    if apply:
        project(connection, item, result)
    return result


def rule_targets(connection, scope, target):
    """Validate a preference target without loading the full UI catalog."""
    if not isinstance(target, str) or len(target) > 4096:
        raise LookupError("Unknown library target")
    if scope == "file":
        exists = connection.execute("SELECT 1 FROM managed_media WHERE path=? UNION ALL "
                                    "SELECT 1 FROM jobs WHERE media=? LIMIT 1", (target, target)).fetchone()
        if exists:
            return file_targets(record(connection, target))
        raise LookupError("Unknown library file")
    key, season = target, None
    if scope == "season":
        try:
            key, raw = target.rsplit(":", 1)
            season = int(raw)
            if target != f"{key}:{season}":
                raise ValueError("Noncanonical season")
        except ValueError as error:
            raise LookupError("Unknown season") from error
    provider, _, item = key.partition(":")
    if provider in {"sonarr", "radarr"} and item.isdecimal() and 0 < int(item) < 2**63:
        paths = connection.execute("SELECT path FROM managed_media WHERE provider=? AND item_id=?",
                                   (provider, int(item)))
    elif provider == "folders":
        prefix = item.rstrip("/") + "/"
        paths = connection.execute("SELECT media FROM jobs WHERE media=? OR (media>=? AND media<?)",
                                   (item, prefix, prefix + "\U0010ffff"))
    else:
        raise LookupError("Unknown library title")
    for path in paths:
        item_record = record(connection, path[0])
        if item_record["key"] == key and (scope == "title" or item_record["season"] == season):
            return [target]
    raise LookupError("Library item is no longer available")


def refresh_batch(database, limit=BATCH_SIZE):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= BATCH_SIZE:
        raise ValueError("Policy batch size must be between 1 and 200")
    # A single read snapshot makes identities, rules, and their revision tokens coherent.
    with database.connect() as connection:
        connection.execute("BEGIN")
        rule_revision = revision(connection)
        scan = dict(connection.execute("SELECT * FROM policy_scan WHERE id=1").fetchone())
        global_rows = connection.execute(
            "SELECT id,media FROM jobs WHERE id>? AND id<=? ORDER BY id LIMIT ?",
            (scan["cursor"], scan["end_id"], max(1, limit // 2) if scan["pending"] else 0),
        ).fetchall()
        paths = dict.fromkeys(r["media"] for r in global_rows)
        # Exclude the global slice so duplicate dirty entries cannot waste the batch.
        for row in connection.execute("SELECT path FROM policy_dirty ORDER BY path LIMIT ?", (limit,)):
            if len(paths) >= limit:
                break
            paths[row[0]] = None
        projected = []
        for path in paths:
            token = connection.execute("SELECT revision FROM policy_inputs WHERE path=?", (path,)).fetchone()
            item = record(connection, path)
            projected.append((item, decide(connection, item), token[0] if token else 0))
    if not projected and not scan["pending"]:
        return 0
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if revision(connection) == rule_revision:
            for item, result, token in projected:
                latest = connection.execute("SELECT revision FROM policy_inputs WHERE path=?",
                                            (item["path"],)).fetchone()
                if (latest[0] if latest else 0) == token:
                    project(connection, item, result, rule_revision, token)
            if scan["pending"]:
                cursor = global_rows[-1]["id"] if global_rows else scan["end_id"]
                connection.execute("UPDATE policy_scan SET cursor=?,pending=? WHERE id=1 "
                                   "AND cursor=? AND end_id=? AND pending=1",
                                   (cursor, int(cursor < scan["end_id"]), scan["cursor"], scan["end_id"]))
    with database.connect() as connection:
        # Count indexed work, not UI records; overlap between the queues counts once.
        return connection.execute(
            "SELECT COUNT(*) FROM (SELECT path FROM policy_dirty UNION SELECT media FROM jobs "
            "WHERE id>(SELECT cursor FROM policy_scan WHERE id=1) "
            "AND id<=(SELECT end_id FROM policy_scan WHERE id=1) "
            "AND (SELECT pending FROM policy_scan WHERE id=1)=1)"
        ).fetchone()[0]
