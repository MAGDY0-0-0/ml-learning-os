"""Download the free, author-published books and papers into library/.

Every entry here is offered for free by its author or publisher — no pirated
copies. Each URL was verified to return a real PDF before being added.

    python -m app.fetch_library --list
    python -m app.fetch_library            # download everything missing
    python -m app.fetch_library --papers   # papers only (small, fast)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass

from app.db import ROOT

LIBRARY = ROOT / "library"


@dataclass(frozen=True)
class Item:
    filename: str
    title: str
    url: str
    kind: str          # "book" | "paper"
    module: str        # which module it supports
    mb: int
    why: str


CATALOGUE: tuple[Item, ...] = (
    # ---------------- books ----------------
    Item("mathematics-for-machine-learning.pdf",
         "Mathematics for Machine Learning", "https://mml-book.github.io/book/mml-book.pdf",
         "book", "M3", 17,
         "The reference for the maths recap. Use the index, never read it linearly."),
    Item("introduction-to-statistical-learning.pdf",
         "An Introduction to Statistical Learning",
         "https://www.statlearning.com/s/ISLR-Seventh-Printing.pdf",
         "book", "M4", 11,
         "The classical-ML spine. Free from the authors."),
    Item("understanding-deep-learning.pdf",
         "Understanding Deep Learning (Prince)",
         "https://github.com/udlbook/udlbook/releases/download/v5.00/UnderstandingDeepLearning_11_21_24_C.pdf",
         "book", "M5", 22,
         "Modern, well-illustrated deep learning. Free PDF from the author."),
    Item("dive-into-deep-learning.pdf",
         "Dive into Deep Learning", "https://d2l.ai/d2l-en.pdf",
         "book", "M5", 45,
         "Maths, code and figures side by side, with PyTorch throughout."),
    Item("little-book-of-deep-learning.pdf",
         "The Little Book of Deep Learning (Fleuret)", "https://fleuret.org/public/lbdl.pdf",
         "book", "M5", 5,
         "~160 phone-sized pages. The fastest honest overview of the whole field."),
    Item("speech-and-language-processing.pdf",
         "Speech and Language Processing (Jurafsky & Martin, 3rd ed draft)",
         "https://web.stanford.edu/~jurafsky/slp3/ed3book.pdf",
         "book", "M6", 18,
         "The standard NLP textbook; the transformer chapters are excellent."),
    Item("foundations-of-data-science.pdf",
         "Foundations of Data Science (Blum, Hopcroft, Kannan)",
         "https://www.cs.cornell.edu/jeh/book.pdf",
         "book", "M4", 3,
         "The theory under the tools: high-dimensional geometry, SVD, clustering."),
    # ---------------- papers ----------------
    Item("paper-attention-is-all-you-need.pdf", "Attention Is All You Need",
         "https://arxiv.org/pdf/1706.03762", "paper", "M6", 3,
         "The transformer paper. Read it after the visual explanations."),
    Item("paper-bert.pdf", "BERT: Pre-training of Deep Bidirectional Transformers",
         "https://arxiv.org/pdf/1810.04805", "paper", "M6", 1,
         "How pre-training plus fine-tuning became the default recipe."),
    Item("paper-lora.pdf", "LoRA: Low-Rank Adaptation of Large Language Models",
         "https://arxiv.org/pdf/2106.09685", "paper", "M6", 2,
         "The technique that makes fine-tuning possible on your 8 GB GPU."),
    Item("paper-leakage-reproducibility.pdf",
         "Leakage and the Reproducibility Crisis in ML-based Science",
         "https://arxiv.org/pdf/2207.07048", "paper", "M4", 1,
         "The source of this app's 8-point leakage checklist. 329 papers, 17 fields."),
    Item("paper-resnet.pdf", "Deep Residual Learning for Image Recognition (ResNet)",
         "https://arxiv.org/pdf/1512.03385", "paper", "M5", 1,
         "Residual connections — why very deep networks became trainable."),
    Item("paper-adam.pdf", "Adam: A Method for Stochastic Optimization",
         "https://arxiv.org/pdf/1412.6980", "paper", "M5", 1,
         "The optimiser you will use by default. Worth knowing what it does."),
)


def download(item: Item) -> bool:
    """Fetch one item with curl. Returns True if the file is present afterwards."""
    dest = LIBRARY / item.filename
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"  have    {item.filename}")
        return True
    LIBRARY.mkdir(parents=True, exist_ok=True)
    print(f"  getting {item.filename}  (~{item.mb} MB) ...", flush=True)
    tmp = dest.with_suffix(".part")
    r = subprocess.run(
        ["curl", "-sL", "--max-time", "600", "-A", "Mozilla/5.0", "-o", str(tmp), item.url],
        capture_output=True,
    )
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 100_000:
        print(f"    FAILED ({item.url})")
        tmp.unlink(missing_ok=True)
        return False
    # sanity: a PDF starts with %PDF
    if tmp.read_bytes()[:4] != b"%PDF":
        print("    FAILED - not a PDF (link probably changed)")
        tmp.unlink(missing_ok=True)
        return False
    tmp.rename(dest)
    print(f"    ok, {dest.stat().st_size / 1024 / 1024:.1f} MB")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show the catalogue, download nothing")
    ap.add_argument("--papers", action="store_true", help="papers only")
    ap.add_argument("--books", action="store_true", help="books only")
    args = ap.parse_args()

    items = CATALOGUE
    if args.papers:
        items = tuple(i for i in items if i.kind == "paper")
    if args.books:
        items = tuple(i for i in items if i.kind == "book")

    if args.list:
        for i in items:
            print(f"  [{i.module}] {i.kind:<5} {i.mb:>3} MB  {i.title}")
            print(f"           {i.why}")
        print(f"\n  {len(items)} items, ~{sum(i.mb for i in items)} MB total")
        return 0

    ok = sum(download(i) for i in items)
    print(f"\n  {ok}/{len(items)} available in {LIBRARY}")
    if ok:
        print("  Now open the app and press 'Reindex my PDFs' to make them searchable.")
    return 0 if ok == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
