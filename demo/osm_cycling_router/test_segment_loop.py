from __future__ import annotations

import unittest

from demo.osm_cycling_router.router import Point
from demo.osm_cycling_router.segment_loop import DirectedSegment, plan_segment_loop, reverse_segment


def segment(name: str, start: tuple[float, float], end: tuple[float, float]) -> DirectedSegment:
    return DirectedSegment(None, name, (start, end), 1_000, 100, {})


class SegmentLoopTests(unittest.TestCase):
    def test_reverse_segment_reverses_geometry_and_excludes_ascent(self) -> None:
        original = segment("climb", (120.0, 30.0), (120.1, 30.0))
        reversed_segment = reverse_segment(original)

        self.assertEqual(reversed_segment.geometry, ((120.1, 30.0), (120.0, 30.0)))
        self.assertEqual(reversed_segment.ascend_m, 0)
        self.assertEqual(reversed_segment.properties["route_direction"], "reverse")

    def test_prefers_order_with_shorter_connectors(self) -> None:
        first = segment("first", (120.0, 30.0), (120.1, 30.0))
        second = segment("second", (120.2, 30.0), (120.3, 30.0))
        third = segment("third", (120.4, 30.0), (120.5, 30.0))
        locations = {(120.1, 30.0, 120.2, 30.0): 1_000, (120.3, 30.0, 120.4, 30.0): 1_000, (120.5, 30.0, 120.0, 30.0): 1_000}

        def connector(origin: Point, destination: Point):
            key = (round(origin.lon, 1), round(origin.lat, 1), round(destination.lon, 1), round(destination.lat, 1))
            distance = locations.get(key, 20_000)
            return {"distance_m": distance, "ascend_m": 0, "details": {}, "raw": {"paths": [{"points": {"coordinates": [[origin.lon, origin.lat], [destination.lon, destination.lat]]}}]}}

        result = plan_segment_loop([first, second, third], target_distance_m=6_000, connector_fetcher=connector, max_candidates=1)[0]
        self.assertEqual([item.name for item in result.segments], ["first", "second", "third"])
        self.assertEqual(result.total_distance_m, 6_000)

    def test_reverse_direction_can_reduce_connector_cost(self) -> None:
        first = segment("first", (120.0, 30.0), (120.1, 30.0))
        second = segment("second", (120.2, 30.0), (120.3, 30.0))

        def connector(origin: Point, destination: Point):
            # The second segment only joins efficiently when it is travelled
            # in reverse: first end -> second end -> second start -> first start.
            key = (round(origin.lon, 1), round(destination.lon, 1))
            distance = 1_000 if key in {(120.1, 120.3), (120.2, 120.0)} else 20_000
            return {"distance_m": distance, "ascend_m": 0, "details": {}, "raw": {"paths": [{"points": {"coordinates": [[origin.lon, origin.lat], [destination.lon, destination.lat]]}}]}}

        result = plan_segment_loop(
            [first, second], target_distance_m=4_000, connector_fetcher=connector,
            allow_reverse=True, max_candidates=1,
        )[0]

        self.assertEqual(result.total_distance_m, 4_000)
        self.assertTrue(any(item.properties.get("route_direction") == "reverse" for item in result.segments))

    def test_fixed_start_is_routed_before_and_after_segment_loop(self) -> None:
        first = segment("first", (120.0, 30.0), (120.1, 30.0))
        second = segment("second", (120.2, 30.0), (120.3, 30.0))

        def connector(origin: Point, destination: Point):
            return {
                "distance_m": 1_000,
                "ascend_m": 0,
                "details": {},
                "raw": {"paths": [{"points": {"coordinates": [[origin.lon, origin.lat], [destination.lon, destination.lat]]}}]},
            }

        result = plan_segment_loop(
            [first, second], target_distance_m=6_000, connector_fetcher=connector,
            max_candidates=1, start=Point(30.0, 119.9), start_name="径山镇",
        )[0]

        self.assertIsNotNone(result.entry_connector)
        self.assertEqual(result.entry_connector.source.name, "径山镇")
        self.assertEqual(result.total_distance_m, 5_000)

    def test_one_closed_segment_can_be_connected_to_a_fixed_city_start(self) -> None:
        loop = segment("已知完整环线", (120.0, 30.0), (120.0, 30.0))

        def connector(origin: Point, destination: Point):
            return {
                "distance_m": 1_000,
                "ascend_m": 0,
                "details": {},
                "raw": {"paths": [{"points": {"coordinates": [[origin.lon, origin.lat], [destination.lon, destination.lat]]}}]},
            }

        result = plan_segment_loop(
            [loop], target_distance_m=3_000, connector_fetcher=connector,
            max_candidates=1, start=Point(30.1, 119.9), start_name="城市起点",
        )[0]

        self.assertEqual(result.total_distance_m, 3_000)
        self.assertEqual(result.connector_distance_m, 2_000)
        self.assertEqual(len(result.connectors), 1)


if __name__ == "__main__":
    unittest.main()
