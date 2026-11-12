"""A PDF page's words as the lines they are printed on — the one grouping
the extracted text, the line positions and a user's template all go by."""
from __future__ import annotations

#: Words whose vertical centers differ by less than this fraction of the
#: word height are on the same printed line.
_LINE_TOLERANCE = 0.5


def group_lines(words: list[tuple]) -> list[list[tuple]]:
    """The page's printed lines as word groups (left to right, top to bottom)."""
    # words: (x0, y0, x1, y1, text, block, line, word)
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple]] = []
    current_center = None
    for word in words:
        center = (word[1] + word[3]) / 2
        height = max(word[3] - word[1], 1.0)
        if current_center is None or abs(center - current_center) > height * _LINE_TOLERANCE:
            lines.append([word])
            current_center = center
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda w: w[0]) for line in lines]
