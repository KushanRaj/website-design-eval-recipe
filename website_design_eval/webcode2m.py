from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag


PathLike = str | os.PathLike[str]


def _read_text(path_or_text: PathLike | str) -> str:
    if isinstance(path_or_text, os.PathLike):
        return Path(path_or_text).read_text(encoding="utf-8", errors="ignore")
    try:
        path = Path(path_or_text)
        if "\n" not in path_or_text and len(path_or_text) < 512 and path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    return str(path_or_text)


class _HTMLMulNode:
    def __init__(self, name: str):
        self.childs: list[_HTMLMulNode] = []
        self.name = name
        self.parent: _HTMLMulNode | None = None
        self.depth = 0

    def add_child(self, child: "_HTMLMulNode") -> None:
        self.childs.append(child)
        child.parent = self
        child.depth = self.depth + 1


def _html2tree(html: str, *, drop_leaves: bool = True) -> list[_HTMLMulNode]:
    """Mirror WebCode2M's `html_tree.html2tree` without importing graphviz."""

    soup = BeautifulSoup(html, "html.parser")
    nodes: list[_HTMLMulNode] = []

    def dfs(html_element: Tag, parent: _HTMLMulNode | None) -> _HTMLMulNode:
        name = html_element.name if html_element.name else str(html_element.strip())
        node = _HTMLMulNode(str(name))
        nodes.append(node)
        if parent is None:
            node.depth = 0
        else:
            parent.add_child(node)

        if html_element.name and html_element.contents:
            for child in html_element.contents:
                if child and str(child).strip() and html_element is not child:
                    if not (drop_leaves and getattr(child, "name", None) is None):
                        dfs(child, node)
        return node

    if soup.html:
        dfs(soup.html, None)
    return nodes


def _collect_all_subtrees(nodes: list[_HTMLMulNode]) -> list[str]:
    subtrees: list[str] = []
    for node in nodes:
        if len(node.childs) == 0:
            continue
        names = [node.name.strip().lower()]
        for child in node.childs:
            names.append(child.name.strip().lower())
        subtrees.append("_".join(names))
    return subtrees


def webcode2m_text_score(reference_html: PathLike | str, candidate_html: PathLike | str) -> dict[str, Any]:
    """WebCode2M visible text BLEU-1 and ROUGE-1 recall."""

    from nltk.translate import bleu_score
    from rouge import Rouge

    soup1 = BeautifulSoup(_read_text(reference_html), "html.parser")
    soup2 = BeautifulSoup(_read_text(candidate_html), "html.parser")
    reference_tokens = soup1.get_text().split()
    candidate_tokens = soup2.get_text().split()

    if not reference_tokens or not candidate_tokens:
        bleu_1 = 0.0
        rouge_1_recall = 0.0
    else:
        bleu_1 = bleu_score.sentence_bleu(
            [reference_tokens],
            candidate_tokens,
            weights=(1.0, 0, 0, 0),
            smoothing_function=bleu_score.SmoothingFunction().method4,
        )
        rouge_scores = Rouge().get_scores(" ".join(candidate_tokens), " ".join(reference_tokens))
        rouge_1_recall = rouge_scores[0]["rouge-1"]["r"]

    return {
        "bleu_1": round(float(bleu_1), 6),
        "rouge_1_recall": round(float(rouge_1_recall), 6),
        "reference_tokens": len(reference_tokens),
        "candidate_tokens": len(candidate_tokens),
        "source": "WebCode2M metrics.py::bleu_rouge",
    }


def webcode2m_dom_score(reference_html: PathLike | str, candidate_html: PathLike | str) -> dict[str, Any]:
    """WebCode2M DOM subtree BLEU/ROUGE.

    This mirrors `research/source-repos/naturalcc/.../evaluation/metrics.py::dom_sim`
    but avoids importing the full metrics module because that file also imports
    optional OCR, ROUGE, CLIP, and graphviz dependencies.
    """

    ref_tree_nodes = _html2tree(_read_text(reference_html))
    cand_tree_nodes = _html2tree(_read_text(candidate_html))
    ref_subtrees = _collect_all_subtrees(ref_tree_nodes)
    cand_subtrees = _collect_all_subtrees(cand_tree_nodes)

    if not ref_subtrees or not cand_subtrees:
        return {
            "tree_bleu": 0.0,
            "tree_rouge_1": 0.0,
            "f1": 0.0,
            "reference_subtrees": len(ref_subtrees),
            "candidate_subtrees": len(cand_subtrees),
            "reference_unique_subtrees": len(set(ref_subtrees)),
            "candidate_unique_subtrees": len(set(cand_subtrees)),
            "source": "WebCode2M metrics.py::dom_sim",
        }

    ref_set = set(ref_subtrees)
    cand_set = set(cand_subtrees)

    unique_match_count = sum(1 for seq in cand_set if seq in ref_set)
    tree_rouge_1 = unique_match_count / len(ref_set)

    candidate_match_count = sum(1 for seq in cand_subtrees if seq in ref_set)
    tree_bleu = candidate_match_count / len(cand_subtrees)
    f1 = 2 * tree_bleu * tree_rouge_1 / (tree_bleu + tree_rouge_1) if tree_bleu + tree_rouge_1 else 0.0

    return {
        "tree_bleu": round(float(tree_bleu), 6),
        "tree_rouge_1": round(float(tree_rouge_1), 6),
        "f1": round(float(f1), 6),
        "matched_unique_subtrees": unique_match_count,
        "matched_candidate_subtrees": candidate_match_count,
        "reference_subtrees": len(ref_subtrees),
        "candidate_subtrees": len(cand_subtrees),
        "reference_unique_subtrees": len(ref_set),
        "candidate_unique_subtrees": len(cand_set),
        "source": "WebCode2M metrics.py::dom_sim",
    }
