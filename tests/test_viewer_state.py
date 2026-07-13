import unittest

from core.image.viewer_state import ViewerState


class ViewerStateTests(unittest.TestCase):
    def test_initial_index_and_mode_are_normalized(self) -> None:
        state = ViewerState(item_count=3, index=20, mode="unknown")

        self.assertEqual(state.index, 2)
        self.assertEqual(state.mode, "paged")

    def test_move_respects_item_boundaries(self) -> None:
        state = ViewerState(item_count=2)

        self.assertFalse(state.move(-1))
        self.assertTrue(state.move(1))
        self.assertFalse(state.move(1))
        self.assertEqual(state.index, 1)

    def test_mode_changes_invalidate_other_mode_requests(self) -> None:
        state = ViewerState(item_count=1)
        paged = state.start_paged_request()

        vertical = state.enter_vertical()
        self.assertGreater(state.paged_generation, paged)

        state.enter_paged()
        self.assertGreater(state.vertical_generation, vertical)

    def test_scroll_updates_index_and_window_includes_adjacent_pages(self) -> None:
        state = ViewerState(item_count=5, index=0)
        offsets = [0, 1000, 2000, 3000, 4000]
        heights = [900] * 5

        self.assertEqual(state.index_for_scroll(offsets, 2050), 2)
        self.assertEqual(
            state.vertical_window(
                offsets,
                heights,
                2050,
                600,
                buffer=0,
                adjacent_pages=1,
            ),
            {1, 2, 3},
        )

    def test_stop_invalidates_requests_and_releases_current_bytes(self) -> None:
        state = ViewerState(item_count=1, alive=True, current_data=b"image")
        paged = state.paged_generation
        vertical = state.vertical_generation

        state.stop()

        self.assertFalse(state.alive)
        self.assertIsNone(state.current_data)
        self.assertGreater(state.paged_generation, paged)
        self.assertGreater(state.vertical_generation, vertical)


if __name__ == "__main__":
    unittest.main()
