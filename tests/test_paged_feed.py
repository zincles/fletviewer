import unittest

from core.paged_feed import PageBatch, PagedFeedState


class PagedFeedStateTests(unittest.TestCase):
    def test_append_deduplicates_items(self):
        state = PagedFeedState[int, int]()
        first = state.begin(replace=True)
        self.assertIsNotNone(first)
        state.complete(first, PageBatch([1, 2], 1), key_of=lambda item: item)
        second = state.begin(1)
        incoming = state.complete(second, PageBatch([2, 3], None), key_of=lambda item: item)
        self.assertEqual(incoming, [3])
        self.assertEqual(state.items, [1, 2, 3])

    def test_replace_invalidates_in_flight_result(self):
        state = PagedFeedState[int, int]()
        old = state.begin(replace=True)
        new = state.begin(replace=True)
        self.assertEqual(state.complete(old, PageBatch([1]), key_of=lambda item: item), [])
        self.assertEqual(state.complete(new, PageBatch([2]), key_of=lambda item: item), [2])
        self.assertEqual(state.items, [2])

    def test_retryable_failure_allows_same_cursor(self):
        state = PagedFeedState[int, int]()
        request = state.begin(replace=True)
        state.fail(request)
        self.assertIsNotNone(state.begin(replace=True))


if __name__ == "__main__":
    unittest.main()
