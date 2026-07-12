import unittest

from scripts.generate_weekly_paper_push import canonical_url, select_papers


class WeeklyPaperPushTests(unittest.TestCase):
    def test_canonicalizes_arxiv_pdf_links(self) -> None:
        self.assertEqual(
            canonical_url("https://arxiv.org/pdf/2607.12345?download=1"),
            "https://arxiv.org/abs/2607.12345",
        )

    def test_selects_only_recent_engineering_papers(self) -> None:
        papers = [
            {
                "title": "Neural operators for computational fluid dynamics",
                "url": "https://arxiv.org/abs/2607.12345",
                "source": "arXiv",
                "published": "2026-07-09",
                "authors": ["A. Engineer"],
                "abstract": "A neural operator surrogate model for CFD simulation.",
            },
            {
                "title": "A language model for poetry",
                "url": "https://arxiv.org/abs/2607.99999",
                "source": "arXiv",
                "published": "2026-07-09",
                "authors": ["B. Writer"],
                "abstract": "A language model for creative writing.",
            },
        ]

        selected = select_papers(papers, "2026-07-10")

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], "https://arxiv.org/abs/2607.12345")
        self.assertIn("summary_en", selected[0])


if __name__ == "__main__":
    unittest.main()
