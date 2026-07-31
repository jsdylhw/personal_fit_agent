from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import URLError

from demo.osm_cycling_router.router import Point, SEMICIRCLE_TO_DEGREES, round_trip, semicircles_to_degrees
from demo.osm_cycling_router.strava_segments import explore_segments


class RouterHelpersTest(unittest.TestCase):
    def test_fit_semicircle_conversion(self):
        self.assertAlmostEqual(semicircles_to_degrees(1 << 30), 90.0)
        self.assertAlmostEqual(semicircles_to_degrees(-(1 << 30)), -90.0)
        self.assertAlmostEqual(SEMICIRCLE_TO_DEGREES * (1 << 31), 180.0)

    def test_graphhopper_point_query_is_lat_lon(self):
        self.assertEqual(Point(lat=31.12345678, lon=121.12345678).query_value(), "31.1234568,121.1234568")

    def test_segment_explorer_reports_tls_failure_without_disabling_verification(self):
        with patch("demo.osm_cycling_router.strava_segments.urlopen", side_effect=URLError("TLS EOF")), \
             patch("demo.osm_cycling_router.strava_segments.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "network/TLS"):
                explore_segments("31.0,121.0,31.1,121.1", "token", retry_attempts=2)

    def test_round_trip_uses_local_flexible_routing_parameters(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        payload = json.dumps({"paths": [{"distance": 10_000, "time": 1_000, "points": {"coordinates": []}}]}).encode()
        with patch("demo.osm_cycling_router.router.build_opener") as build:
            build.return_value.open.return_value = Response(payload)
            round_trip(Point(30.0, 121.0), distance_m=10_000, seed=4)

        request_url = build.return_value.open.call_args.args[0]
        query = parse_qs(urlsplit(request_url).query)
        self.assertEqual(query["algorithm"], ["round_trip"])
        self.assertEqual(query["ch.disable"], ["true"])
        self.assertEqual(query["round_trip.distance"], ["10000"])
        self.assertEqual(query["round_trip.seed"], ["4"])


if __name__ == "__main__":
    unittest.main()
