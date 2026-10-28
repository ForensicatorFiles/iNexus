"""Load supplemental "learned place" and Significant Location visits from
Local.sqlite (routined), used to corroborate/enrich Cache.sqlite and
Cloud-V2.sqlite stays or act as a standalone stay source when Cache.sqlite
has rolled over."""

import sqlite3
from ..constants import DEFAULT_MIN_STAY_MINUTES
from ..db import _open_sqlite_or_die
from ..utils import unix_ts


def load_local_db(path, min_stay_minutes=DEFAULT_MIN_STAY_MINUTES):
    """
    Loads visits and trip segments from a "Local.sqlite" routined database.
    Uses PRAGMA table_info() to dynamically adapt to column name variations
    across iOS versions (e.g. ZLOCATIONUNCERTAINTY vs
    ZLOCATIONHORIZONTALUNCERTAINTY, or coordinates stored on the parent LOI
    table).

    Returns (pings, visits, trips) tagged with source_db="local".
    """
    conn, cur = _open_sqlite_or_die(path)

    def _table_cols(table):
        try:
            cur.execute(f"PRAGMA table_info({table})")
            return {row[1] for row in cur.fetchall()}
        except sqlite3.OperationalError:
            return set()

    def _has_rows(table, where=""):
        try:
            cur.execute(f"SELECT 1 FROM {table} {where} LIMIT 1")
            return cur.fetchone() is not None
        except sqlite3.OperationalError:
            return False

    def _pick_col(alias, cols_set, candidates, as_name):
        """Returns 'alias.COL AS as_name' for the first matching column, or 'NULL AS as_name'."""
        for c in candidates:
            if c in cols_set:
                return f"{alias}.{c} AS {as_name}"
        return f"NULL AS {as_name}"

    visits = []
    trips = []

    lv_cols  = _table_cols("ZRTLEARNEDVISITMO")
    loi_v_cols = _table_cols("ZRTLEARNEDLOCATIONOFINTERESTVISITMO")

    # ── Schema Variant 1: ZRTLEARNEDVISITMO (Modern routined Local.sqlite) ──
    if lv_cols and _has_rows("ZRTLEARNEDVISITMO", "WHERE ZENTRYDATE IS NOT NULL"):
        lp_cols = _table_cols("ZRTLEARNEDPLACEMO")
        mi_cols = _table_cols("ZRTMAPITEMMO")
        ad_cols = _table_cols("ZRTADDRESSMO")
        dv_cols = _table_cols("ZRTDEVICEMO")

        lat_expr  = _pick_col("lv", lv_cols, ["ZLOCATIONLATITUDE", "ZLATITUDE"], "v_lat")
        lng_expr  = _pick_col("lv", lv_cols, ["ZLOCATIONLONGITUDE", "ZLONGITUDE"], "v_lng")
        hacc_expr = _pick_col("lv", lv_cols, [
            "ZLOCATIONUNCERTAINTY",
            "ZLOCATIONHORIZONTALUNCERTAINTY",
            "ZHORIZONTALUNCERTAINTY",
            "ZHORIZONTALACCURACY",
            "ZUNCERTAINTY",
        ], "v_hacc")
        conf_expr = _pick_col("lv", lv_cols, ["ZCONFIDENCE"], "v_conf")
        dpc_expr  = _pick_col("lv", lv_cols, ["ZDATAPOINTCOUNT"], "v_dpc")

        joins = []
        extra_selects = [
            "NULL AS place_name",
            "NULL AS place_category",
            "NULL AS ZTHOROUGHFARE",
            "NULL AS ZSUBLOCALITY",
            "NULL AS ZLOCALITY",
            "NULL AS ZADMINISTRATIVEAREA",
            "NULL AS ZCOUNTRY",
            "NULL AS ZDEVICENAME",
            "NULL AS ZDEVICEMODEL",
            "NULL AS ZDEVICECLASS",
        ]

        if "ZPLACE" in lv_cols and lp_cols:
            joins.append("LEFT JOIN ZRTLEARNEDPLACEMO lp ON lp.Z_PK = lv.ZPLACE")
            if "ZMAPITEM" in lp_cols and mi_cols:
                joins.append("LEFT JOIN ZRTMAPITEMMO mi ON mi.Z_PK = lp.ZMAPITEM")
                extra_selects[0] = _pick_col("mi", mi_cols, ["ZNAME"], "place_name")
                extra_selects[1] = _pick_col("mi", mi_cols, ["ZCATEGORY"], "place_category")
                if "ZADDRESS" in mi_cols and ad_cols:
                    joins.append("LEFT JOIN ZRTADDRESSMO ad ON ad.Z_PK = mi.ZADDRESS")
                    extra_selects[2] = _pick_col("ad", ad_cols, ["ZTHOROUGHFARE"], "ZTHOROUGHFARE")
                    extra_selects[3] = _pick_col("ad", ad_cols, ["ZSUBLOCALITY"], "ZSUBLOCALITY")
                    extra_selects[4] = _pick_col("ad", ad_cols, ["ZLOCALITY"], "ZLOCALITY")
                    extra_selects[5] = _pick_col("ad", ad_cols, ["ZADMINISTRATIVEAREA"], "ZADMINISTRATIVEAREA")
                    extra_selects[6] = _pick_col("ad", ad_cols, ["ZCOUNTRY"], "ZCOUNTRY")

        if "ZDEVICE" in lv_cols and dv_cols:
            joins.append("LEFT JOIN ZRTDEVICEMO dv ON dv.Z_PK = lv.ZDEVICE")
            extra_selects[7] = _pick_col("dv", dv_cols, ["ZDEVICENAME"], "ZDEVICENAME")
            extra_selects[8] = _pick_col("dv", dv_cols, ["ZDEVICEMODEL"], "ZDEVICEMODEL")
            extra_selects[9] = _pick_col("dv", dv_cols, ["ZDEVICECLASS"], "ZDEVICECLASS")

        where_clause = "WHERE lv.ZENTRYDATE IS NOT NULL"
        if "ZCONFIDENCE" in lv_cols:
            where_clause += " AND (lv.ZCONFIDENCE IS NULL OR lv.ZCONFIDENCE >= 0.5)"

        sql = f"""
            SELECT lv.Z_PK, lv.ZENTRYDATE, lv.ZEXITDATE,
                   {lat_expr}, {lng_expr}, {hacc_expr}, {conf_expr}, {dpc_expr},
                   {', '.join(extra_selects)}
            FROM ZRTLEARNEDVISITMO lv
            {' '.join(joins)}
            {where_clause}
            ORDER BY lv.ZENTRYDATE
        """
        cur.execute(sql)

        for r in cur.fetchall():
            d = dict(r)
            lat, lng = d.get("v_lat"), d.get("v_lng")
            if lat is None or lng is None:
                continue
            entry = unix_ts(d["ZENTRYDATE"])
            exit_ = unix_ts(d["ZEXITDATE"])
            dur   = (exit_ - entry) if (entry and exit_) else None
            if dur and dur < min_stay_minutes * 60:
                continue
            address_parts = [
                d.get("ZTHOROUGHFARE"), d.get("ZSUBLOCALITY"),
                d.get("ZLOCALITY"), d.get("ZADMINISTRATIVEAREA"),
                d.get("ZCOUNTRY")
            ]
            address = ", ".join(p for p in address_parts if p and isinstance(p, str))
            device_label = (
                d.get("ZDEVICENAME") or d.get("ZDEVICEMODEL") or d.get("ZDEVICECLASS")
            )
            visits.append({
                "entry":            entry,
                "exit":             exit_,
                "duration":         dur,
                "lat":              lat,
                "lng":              lng,
                "hacc":             d.get("v_hacc"),
                "conf":             d.get("v_conf"),
                "source_schema":    "local_learned",
                "source_db":        "local",
                "learned_zpk":      d["Z_PK"],
                "place_name":       d.get("place_name") if isinstance(d.get("place_name"), str) else None,
                "place_category":   d.get("place_category"),
                "address":          address or None,
                "device_name":      device_label,
                "data_point_count": d.get("v_dpc"),
            })

    # ── Schema Variant 2: ZRTLEARNEDLOCATIONOFINTERESTVISITMO (LOI table) ────
    elif loi_v_cols and _has_rows("ZRTLEARNEDLOCATIONOFINTERESTVISITMO", "WHERE ZENTRYDATE IS NOT NULL"):
        loi_cols = _table_cols("ZRTLEARNEDLOCATIONOFINTERESTMO")

        v_lat_expr  = _pick_col("lv", loi_v_cols, ["ZLOCATIONLATITUDE", "ZLATITUDE"], "v_lat")
        v_lng_expr  = _pick_col("lv", loi_v_cols, ["ZLOCATIONLONGITUDE", "ZLONGITUDE"], "v_lng")
        v_hacc_expr = _pick_col("lv", loi_v_cols, [
            "ZLOCATIONUNCERTAINTY",
            "ZLOCATIONHORIZONTALUNCERTAINTY",
            "ZHORIZONTALUNCERTAINTY",
            "ZHORIZONTALACCURACY",
            "ZUNCERTAINTY",
        ], "v_hacc")
        v_conf_expr = _pick_col("lv", loi_v_cols, ["ZCONFIDENCE"], "v_conf")
        v_dpc_expr  = _pick_col("lv", loi_v_cols, ["ZDATAPOINTCOUNT"], "v_dpc")

        join_sql = ""
        loi_lat_expr  = "NULL AS loi_lat"
        loi_lng_expr  = "NULL AS loi_lng"
        loi_hacc_expr = "NULL AS loi_hacc"
        loi_fk = "ZLOCATIONOFINTEREST" if "ZLOCATIONOFINTEREST" in loi_v_cols else None

        if loi_fk and loi_cols:
            join_sql = f"LEFT JOIN ZRTLEARNEDLOCATIONOFINTERESTMO loi ON loi.Z_PK = lv.{loi_fk}"
            loi_lat_expr  = _pick_col("loi", loi_cols, ["ZLOCATIONLATITUDE", "ZLATITUDE"], "loi_lat")
            loi_lng_expr  = _pick_col("loi", loi_cols, ["ZLOCATIONLONGITUDE", "ZLONGITUDE"], "loi_lng")
            loi_hacc_expr = _pick_col("loi", loi_cols, [
                "ZLOCATIONUNCERTAINTY",
                "ZLOCATIONHORIZONTALUNCERTAINTY",
                "ZHORIZONTALUNCERTAINTY",
                "ZUNCERTAINTY",
            ], "loi_hacc")

        sql = f"""
            SELECT lv.Z_PK, lv.ZENTRYDATE, lv.ZEXITDATE,
                   {v_lat_expr}, {v_lng_expr}, {v_hacc_expr}, {v_conf_expr}, {v_dpc_expr},
                   {loi_lat_expr}, {loi_lng_expr}, {loi_hacc_expr}
            FROM ZRTLEARNEDLOCATIONOFINTERESTVISITMO lv
            {join_sql}
            WHERE lv.ZENTRYDATE IS NOT NULL
            ORDER BY lv.ZENTRYDATE
        """
        cur.execute(sql)

        for r in cur.fetchall():
            d = dict(r)
            conf = d.get("v_conf")
            if conf is not None and conf < 0.5:
                continue
            entry = unix_ts(d["ZENTRYDATE"])
            exit_ = unix_ts(d["ZEXITDATE"])
            dur   = (exit_ - entry) if (entry and exit_) else None
            if dur and dur < min_stay_minutes * 60:
                continue
            lat  = d.get("v_lat") if d.get("v_lat") is not None else d.get("loi_lat")
            lng  = d.get("v_lng") if d.get("v_lng") is not None else d.get("loi_lng")
            hacc = d.get("v_hacc") if d.get("v_hacc") is not None else d.get("loi_hacc")
            if lat is None or lng is None:
                continue
            visits.append({
                "entry":            entry,
                "exit":             exit_,
                "duration":         dur,
                "lat":              lat,
                "lng":              lng,
                "hacc":             hacc,
                "conf":             conf,
                "source_schema":    "local_loi",
                "source_db":        "local",
                "learned_zpk":      d["Z_PK"],
                "place_name":       None,
                "place_category":   None,
                "address":          None,
                "device_name":      None,
                "data_point_count": d.get("v_dpc"),
            })

    # ── Transitions / Trips in Local.sqlite ──────────────────────────────────
    tr_cols = _table_cols("ZRTLEARNEDTRANSITIONMO") or _table_cols("ZRTLEARNEDLOCATIONOFINTERESTTRANSITIONMO")
    tr_table = (
        "ZRTLEARNEDTRANSITIONMO"
        if _table_cols("ZRTLEARNEDTRANSITIONMO")
        else ("ZRTLEARNEDLOCATIONOFINTERESTTRANSITIONMO" if _table_cols("ZRTLEARNEDLOCATIONOFINTERESTTRANSITIONMO") else None)
    )
    if tr_table and _has_rows(tr_table, "WHERE ZSTARTDATE IS NOT NULL"):
        stop_expr = _pick_col("tr", tr_cols, ["ZSTOPDATE", "ZENDDATE"], "stop_date")
        mode_expr = _pick_col("tr", tr_cols, ["ZPREDOMINANTMOTIONACTIVITYTYPE", "ZMODEOFTRANSPORTATION"], "mode_type")
        orig_expr = _pick_col("tr", tr_cols, ["ZORIGIN", "ZVISITIDENTIFIERORIGIN"], "orig_zpk")
        dest_expr = _pick_col("tr", tr_cols, ["ZDESTINATION", "ZVISITIDENTIFIERDESTINATION"], "dest_zpk")

        cur.execute(f"""
            SELECT tr.Z_PK, tr.ZSTARTDATE, {stop_expr}, {mode_expr}, {orig_expr}, {dest_expr}
            FROM {tr_table} tr
            WHERE tr.ZSTARTDATE IS NOT NULL
            ORDER BY tr.ZSTARTDATE
        """)
        for r in cur.fetchall():
            d = dict(r)
            trips.append({
                "ZSTARTDATE":            d["ZSTARTDATE"],
                "ZENDDATE":              d.get("stop_date"),
                "ZMODEOFTRANSPORTATION": d.get("mode_type"),
                "ZTRIPDISTANCE_M":       None,
                "source_schema":         "local_learned",
                "source_db":             "local",
                "learned_zpk":           d["Z_PK"],
                "origin_visit_zpk":      d.get("orig_zpk"),
                "destination_visit_zpk": d.get("dest_zpk"),
            })

    conn.close()
    return [], visits, trips