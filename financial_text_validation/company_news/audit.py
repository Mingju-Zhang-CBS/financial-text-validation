"""Bounded metadata-only WRDS audit using an existing libpq service/passfile."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def audit(output):
    import psycopg2

    output.mkdir(parents=True, exist_ok=False)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "read-only metadata and table SELECT privileges; no news rows",
              "status": "attempted", "coverage_verified": False,
              "mapping_loss_verified": False, "rights": "unresolved",
              "tables": [], "columns": []}
    connection = None
    try:
        options = {"sslmode": "require", "connect_timeout": 15,
                   "application_name": "company_news_metadata_audit"}
        if os.getenv("PGSERVICE"):
            options["service"] = os.environ["PGSERVICE"]
        else:
            options.update(host="wrds-pgdata.wharton.upenn.edu", port=9737, dbname="wrds")
            if os.getenv("PGUSER"):
                options["user"] = os.environ["PGUSER"]
            else:
                passfile = Path(os.getenv("PGPASSFILE", str(Path.home() / "AppData/Roaming/postgresql/pgpass.conf")))
                entries = [line.split(":", 4) for line in passfile.read_text().splitlines()
                           if line and not line.startswith("#")]
                matches = [entry for entry in entries if entry[0] == options["host"]]
                if len(matches) != 1:
                    raise ValueError("Unique service entry required")
                options["user"] = matches[0][3]
                options["port"] = int(matches[0][1])
        connection = psycopg2.connect(**options)
        connection.set_session(readonly=True, autocommit=True)
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '20s'")
            cursor.execute("SELECT table_schema, table_name, "
                           "has_table_privilege(quote_ident(table_schema)||'.'||quote_ident(table_name), 'SELECT') "
                           "FROM information_schema.tables WHERE table_schema ~ %s ORDER BY 1,2 LIMIT 2500",
                           ("^(ravenpack|rpna|rpa|crsp)",))
            report["tables"] = [list(row) for row in cursor.fetchall()]
            cursor.execute("SELECT table_schema, table_name, column_name, data_type "
                           "FROM information_schema.columns WHERE table_schema ~ %s ORDER BY 1,2,ordinal_position LIMIT 30000",
                           ("^(ravenpack|rpna|rpa|crsp)",))
            report["columns"] = [list(row) for row in cursor.fetchall()]
        report["status"] = "metadata-inspected; semantics/coverage/rights still pending"
    except Exception as error:
        message = str(error).lower()
        report["status"] = "blocked"
        report["failure_class"] = type(error).__name__
        report["reason"] = ("server-authentication-rejected" if "authentication failed" in message
                            else "connection-or-configuration-failed")
    finally:
        if connection is not None:
            connection.close()
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ["status", "coverage_verified", "rights"]}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    audit(arguments.output)
