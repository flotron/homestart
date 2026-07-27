"""SQLite-backed system and network metric storage."""

import sqlite3
import time
from pathlib import Path


class MetricStore:
    def __init__(self, db_path, retention_days=7):
        self.db_path = Path(db_path)
        self.retention_days = int(retention_days)

    @property
    def retention_seconds(self):
        return self.retention_days * 86400

    def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS system_metrics (
              captured_at INTEGER PRIMARY KEY,
              cpu REAL,
              memory REAL,
              gpu REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS network_metrics (
              captured_at INTEGER PRIMARY KEY,
              rx_bps REAL,
              tx_bps REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS container_network_metrics (
              captured_at INTEGER,
              container_key TEXT,
              name TEXT,
              rx_bytes REAL,
              tx_bytes REAL,
              rx_bps REAL,
              tx_bps REAL,
              PRIMARY KEY (captured_at, container_key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS host_network_estimates (
              captured_at INTEGER,
              identity_key TEXT,
              name TEXT,
              kind TEXT,
              confidence TEXT,
              rx_bytes REAL,
              tx_bytes REAL,
              rx_bps REAL,
              tx_bps REAL,
              PRIMARY KEY (captured_at, identity_key)
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(system_metrics)")
        }
        for name in ("rx_bps", "tx_bps", "temperature"):
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE system_metrics ADD COLUMN {name} REAL"
                )
        return connection

    def record_system(self, payload, captured_at=None):
        captured_at = int(captured_at or payload.get("timestamp") or time.time())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO system_metrics
                  (captured_at, cpu, memory, gpu, rx_bps, tx_bps, temperature)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    captured_at,
                    payload.get("cpu", {}).get("percent"),
                    payload.get("memory", {}).get("percent"),
                    payload.get("gpu", {}).get("percent"),
                    payload.get("network", {}).get("rx_bps"),
                    payload.get("network", {}).get("tx_bps"),
                    payload.get("temperature", {}).get("celsius"),
                ),
            )
            connection.execute(
                "DELETE FROM system_metrics WHERE captured_at < ?",
                (captured_at - self.retention_seconds,),
            )

    def record_network(self, payload, captured_at=None):
        captured_at = int(captured_at or payload.get("timestamp") or time.time())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO network_metrics
                  (captured_at, rx_bps, tx_bps)
                VALUES (?, ?, ?)
                """,
                (captured_at, payload.get("rx_bps"), payload.get("tx_bps")),
            )
            connection.execute(
                "DELETE FROM network_metrics WHERE captured_at < ?",
                (captured_at - self.retention_seconds,),
            )

    def record_container_network(self, samples, captured_at=None):
        captured_at = int(captured_at or time.time())
        rows = [
            (
                captured_at,
                str(sample.get("key") or sample.get("name") or ""),
                str(sample.get("name") or "Unknown container"),
                max(0, float(sample.get("rx_bps") or 0)
                    * float(sample.get("sample_seconds") or 2)),
                max(0, float(sample.get("tx_bps") or 0)
                    * float(sample.get("sample_seconds") or 2)),
                max(0, float(sample.get("rx_bps") or 0)),
                max(0, float(sample.get("tx_bps") or 0)),
            )
            for sample in samples
            if sample.get("key") or sample.get("name")
        ]
        if not rows:
            return
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO container_network_metrics
                  (captured_at, container_key, name, rx_bytes, tx_bytes, rx_bps, tx_bps)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.execute(
                "DELETE FROM container_network_metrics WHERE captured_at < ?",
                (captured_at - self.retention_seconds,),
            )

    def record_host_estimates(
        self, samples, network, container_samples, captured_at=None,
    ):
        captured_at = int(captured_at or time.time())
        sample_seconds = max(.001, float(network.get("sample_seconds") or 2))
        rows = []
        estimated_rx = estimated_tx = 0
        for sample in samples:
            rx_bytes = max(0, float(sample.get("rx_bytes") or 0))
            tx_bytes = max(0, float(sample.get("tx_bytes") or 0))
            estimated_rx += rx_bytes
            estimated_tx += tx_bytes
            rows.append((
                captured_at,
                str(sample.get("key") or sample.get("name") or ""),
                str(sample.get("name") or "Unknown process"),
                str(sample.get("kind") or "process"),
                str(sample.get("confidence") or "medium"),
                rx_bytes,
                tx_bytes,
                max(0, float(sample.get("rx_bps") or 0)),
                max(0, float(sample.get("tx_bps") or 0)),
            ))

        measured_rx = sum(
            max(0, float(item.get("rx_bps") or 0)
                * float(item.get("sample_seconds") or sample_seconds))
            for item in container_samples
        )
        measured_tx = sum(
            max(0, float(item.get("tx_bps") or 0)
                * float(item.get("sample_seconds") or sample_seconds))
            for item in container_samples
        )
        host_rx = max(0, float(network.get("rx_bps") or 0) * sample_seconds)
        host_tx = max(0, float(network.get("tx_bps") or 0) * sample_seconds)
        unattributed_rx = max(0, host_rx - measured_rx - estimated_rx)
        unattributed_tx = max(0, host_tx - measured_tx - estimated_tx)
        if unattributed_rx or unattributed_tx:
            rows.append((
                captured_at,
                "unattributed",
                "Unattributed traffic",
                "unattributed",
                "low",
                unattributed_rx,
                unattributed_tx,
                unattributed_rx / sample_seconds,
                unattributed_tx / sample_seconds,
            ))
        if not rows:
            return
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO host_network_estimates
                  (captured_at, identity_key, name, kind, confidence,
                   rx_bytes, tx_bytes, rx_bps, tx_bps)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.execute(
                "DELETE FROM host_network_estimates WHERE captured_at < ?",
                (captured_at - self.retention_seconds,),
            )

    def network_ranking(self, period=3600, limit=12, now=None):
        try:
            period = int(period)
        except (TypeError, ValueError):
            period = 3600
        if period not in {60, 3600, 86400}:
            raise ValueError("Ranking period must be 60, 3600, or 86400 seconds")
        limit = max(1, min(50, int(limit or 12)))
        generated_at = int(now or time.time())
        since = generated_at - period
        with self.connect() as connection:
            container_bounds = connection.execute(
                """
                SELECT MIN(captured_at), MAX(captured_at), COUNT(*)
                FROM container_network_metrics
                WHERE captured_at >= ?
                """,
                (since,),
            ).fetchone()
            host_bounds = connection.execute(
                """
                SELECT MIN(captured_at), MAX(captured_at), COUNT(*)
                FROM host_network_estimates
                WHERE captured_at >= ?
                """,
                (since,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT container_key,
                       name,
                       SUM(rx_bytes) AS rx_bytes,
                       SUM(tx_bytes) AS tx_bytes,
                       AVG(rx_bps) AS rx_avg_bps,
                       AVG(tx_bps) AS tx_avg_bps,
                       MAX(rx_bps) AS rx_peak_bps,
                       MAX(tx_bps) AS tx_peak_bps,
                       COUNT(*) AS sample_count,
                       MIN(captured_at) AS first_captured_at,
                       MAX(captured_at) AS last_captured_at
                FROM container_network_metrics
                WHERE captured_at >= ?
                GROUP BY container_key, name
                HAVING (SUM(rx_bytes) + SUM(tx_bytes)) > 0
                ORDER BY (SUM(rx_bytes) + SUM(tx_bytes)) DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
            estimated_rows = connection.execute(
                """
                SELECT identity_key,
                       name,
                       kind,
                       confidence,
                       SUM(rx_bytes) AS rx_bytes,
                       SUM(tx_bytes) AS tx_bytes,
                       AVG(rx_bps) AS rx_avg_bps,
                       AVG(tx_bps) AS tx_avg_bps,
                       MAX(rx_bps) AS rx_peak_bps,
                       MAX(tx_bps) AS tx_peak_bps,
                       COUNT(*) AS sample_count,
                       MIN(captured_at) AS first_captured_at,
                       MAX(captured_at) AS last_captured_at
                FROM host_network_estimates
                WHERE captured_at >= ?
                GROUP BY identity_key, name, kind, confidence
                HAVING (SUM(rx_bytes) + SUM(tx_bytes)) > 0
                ORDER BY (SUM(rx_bytes) + SUM(tx_bytes)) DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()

        def observed_seconds(bounds):
            if not bounds or not bounds[2]:
                return 0
            return min(period, max(2, int(bounds[1]) - int(bounds[0]) + 2))

        def ranked(values, coverage_seconds):
            items = []
            for index, row in enumerate(values, 1):
                item = dict(row)
                item["rank"] = index
                item["total_bytes"] = (
                    float(item.get("rx_bytes") or 0)
                    + float(item.get("tx_bytes") or 0)
                )
                item["observed_seconds"] = max(1, coverage_seconds)
                item["average_bps"] = (
                    item["total_bytes"] / item["observed_seconds"]
                )
                items.append(item)
            return items

        docker_coverage = observed_seconds(container_bounds)
        host_coverage = observed_seconds(host_bounds)
        return {
            "ok": True,
            "period_seconds": period,
            "generated_at": generated_at,
            "docker_observed_seconds": docker_coverage,
            "host_observed_seconds": host_coverage,
            "items": ranked(rows, docker_coverage),
            "estimated_items": ranked(estimated_rows, host_coverage),
            "scope": "docker_containers",
            "estimated_scope": "host_tcp_processes",
        }

    def history(self, hours=24, network_interface="", now=None):
        automatic = str(hours).lower() == "auto"
        try:
            hours = 168 if automatic else max(1, min(168, int(hours)))
        except (TypeError, ValueError):
            hours = 24
        server_timestamp = int(now or time.time())
        since = server_timestamp - hours * 3600
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT captured_at, cpu, memory, gpu, rx_bps, tx_bps, temperature
                FROM system_metrics
                WHERE captured_at >= ?
                ORDER BY captured_at
                """,
                (since,),
            ).fetchall()
            network_bounds = connection.execute(
                """
                SELECT MIN(captured_at), MAX(captured_at), COUNT(*)
                FROM network_metrics
                WHERE captured_at BETWEEN ? AND ?
                """,
                (since, server_timestamp + 5),
            ).fetchone()
            latest_network_row = connection.execute(
                """
                SELECT captured_at, rx_bps, tx_bps
                FROM network_metrics
                WHERE captured_at BETWEEN ? AND ?
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (since, server_timestamp + 5),
            ).fetchone()
            available_span = max(
                0, (network_bounds[1] or 0) - (network_bounds[0] or 0),
            )
            bucket_seconds = max(2, int((available_span + 1199) // 1200))
            network_rows = connection.execute(
                """
                SELECT (captured_at / ?) * ? AS captured_at,
                       MAX(rx_bps) AS rx_bps,
                       MAX(tx_bps) AS tx_bps,
                       AVG(rx_bps) AS rx_avg_bps,
                       AVG(tx_bps) AS tx_avg_bps,
                       COUNT(*) AS sample_count
                FROM network_metrics
                WHERE captured_at BETWEEN ? AND ?
                GROUP BY captured_at / ?
                ORDER BY captured_at
                """,
                (
                    bucket_seconds, bucket_seconds, since,
                    server_timestamp + 5, bucket_seconds,
                ),
            ).fetchall()
            if not network_rows:
                network_rows = connection.execute(
                    """
                    SELECT captured_at, rx_bps, tx_bps
                    FROM system_metrics
                    WHERE captured_at >= ?
                    ORDER BY captured_at
                    """,
                    (since,),
                ).fetchall()

        network_points = []
        for row in network_rows:
            point = dict(row)
            point.setdefault("rx_avg_bps", point.get("rx_bps"))
            point.setdefault("tx_avg_bps", point.get("tx_bps"))
            point.setdefault("sample_count", 1)
            network_points.append(point)
        gap_threshold = max(10, bucket_seconds * 3)
        gaps = [
            {
                "start": previous["captured_at"],
                "end": current["captured_at"],
                "seconds": current["captured_at"] - previous["captured_at"],
            }
            for previous, current in zip(network_points, network_points[1:])
            if current["captured_at"] - previous["captured_at"] > gap_threshold
        ]
        latest_sample = latest_network_row["captured_at"] if latest_network_row else None
        return {
            "ok": True,
            "hours": "auto" if automatic else hours,
            "server_timestamp": server_timestamp,
            "network_interface": network_interface,
            "points": [dict(row) for row in rows],
            "network_points": network_points,
            "network_sample_seconds": 2,
            "network_bucket_seconds": bucket_seconds,
            "network_status": {
                "stored_samples": int(network_bounds[2] or 0),
                "first_timestamp": network_bounds[0],
                "last_timestamp": network_bounds[1],
                "current_timestamp": latest_sample,
                "current_rx_bps": (
                    latest_network_row["rx_bps"] if latest_network_row else None
                ),
                "current_tx_bps": (
                    latest_network_row["tx_bps"] if latest_network_row else None
                ),
                "last_sample_age_seconds": (
                    max(0, server_timestamp - latest_sample)
                    if latest_sample else None
                ),
                "gap_count": len(gaps),
                "largest_gap_seconds": max(
                    (gap["seconds"] for gap in gaps), default=0,
                ),
            },
            "retention_days": self.retention_days,
        }
