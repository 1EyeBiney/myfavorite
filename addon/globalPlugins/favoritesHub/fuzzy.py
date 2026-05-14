# Favorites Hub — NVDA 2026.1 Global Plugin
# fuzzy.py: Pure-Python string scoring algorithm for the Quick-Pick overlay.
#
# Design goals:
#   • Zero external dependencies — only the Python 3.13 standard library.
#   • Lightweight: intended to be called in a tight loop over hundreds of
#     entries as the user types in the Quick-Pick search box.
#   • Returns a float score: 0.0 means "no match at all"; higher values
#     indicate stronger relevance.  Callers should filter out 0.0 scores
#     and sort the remainder in descending order.
#
# Scoring tiers (approximate upper bounds shown):
#   1 000   Exact case-sensitive match
#     950   Exact case-insensitive match
#     900   Query is a case-insensitive prefix of the text
#     800+  Query is a case-insensitive substring (bonus for earlier position
#           and for the original case matching exactly)
#     500+  Query starts at a word boundary inside the text
#     100+  Query matches as a non-contiguous subsequence (bonus for
#           consecutive runs, compactness, early occurrence, high coverage)
#       0   No match
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

__all__ = ["score", "rank"]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def score(query: str, text: str) -> float:
	"""Return a relevance score for *query* against *text*.

	Both arguments are compared case-insensitively.  A bonus is awarded when
	the original (case-sensitive) characters also match.

	Args:
		query: The user's search string (may be empty).
		text:  The candidate string to score against.

	Returns:
		0.0  — query is empty, text is empty, or no characters of query appear
		       in text in order.
		>0.0 — some degree of match; higher is better.
	"""
	if not query or not text:
		return 0.0

	n_q = len(query)
	n_t = len(text)

	# A query longer than the text can never be a subsequence.
	if n_q > n_t:
		return 0.0

	q_low = query.lower()
	t_low = text.lower()

	# ------------------------------------------------------------------
	# Tier 1: exact match
	# ------------------------------------------------------------------
	if query == text:
		return 1000.0
	if q_low == t_low:
		return 950.0

	# ------------------------------------------------------------------
	# Tier 2: prefix match
	# ------------------------------------------------------------------
	if t_low.startswith(q_low):
		# Bonus for case-matching the prefix in the original
		case_bonus = 20.0 if text.startswith(query) else 0.0
		# Bonus for short text (query covers a high fraction)
		coverage_bonus = (n_q / n_t) * 30.0
		return 900.0 + case_bonus + coverage_bonus

	# ------------------------------------------------------------------
	# Tier 3: substring match
	# ------------------------------------------------------------------
	idx = t_low.find(q_low)
	if idx >= 0:
		# Earlier position = higher score
		position_bonus = (1.0 - idx / n_t) * 80.0
		case_bonus = 20.0 if text[idx: idx + n_q] == query else 0.0
		return 800.0 + position_bonus + case_bonus

	# ------------------------------------------------------------------
	# Tier 4: word-boundary prefix
	# (query is a prefix of one of the whitespace/separator-delimited words)
	# ------------------------------------------------------------------
	if _matches_word_boundary(q_low, t_low):
		return 500.0

	# ------------------------------------------------------------------
	# Tier 5: non-contiguous subsequence
	# ------------------------------------------------------------------
	return _subsequence_score(q_low, t_low)


def rank(
	query: str,
	candidates: list[str],
	*,
	min_score: float = 0.0,
) -> list[tuple[float, str]]:
	"""Score every candidate against *query* and return a sorted result list.

	Args:
		query:      The search string.
		candidates: List of strings to score.
		min_score:  Exclude candidates with score <= this value (default 0.0,
		            which excludes exact zero-score items).

	Returns:
		A list of (score, candidate) tuples sorted by score descending.
		Candidates with score <= min_score are omitted.
	"""
	results: list[tuple[float, str]] = []
	for candidate in candidates:
		s = score(query, candidate)
		if s > min_score:
			results.append((s, candidate))
	results.sort(key=lambda pair: pair[0], reverse=True)
	return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _matches_word_boundary(q_low: str, t_low: str) -> bool:
	"""Return True if *q_low* is a prefix of any word in *t_low*.

	Words are delimited by spaces, hyphens, underscores, and forward slashes
	(the last two are common in file paths).
	"""
	start = 0
	n_t = len(t_low)
	n_q = len(q_low)
	in_word = False

	for i, ch in enumerate(t_low):
		is_delim = ch in (" ", "-", "_", "/", "\\", ".")
		if not in_word and not is_delim:
			in_word = True
			start = i
		elif in_word and is_delim:
			in_word = False
			# Check the word we just finished
			if t_low[start: start + n_q] == q_low:
				return True

	# Check the last word (if the string does not end with a delimiter)
	if in_word and start < n_t:
		if t_low[start: start + n_q] == q_low:
			return True

	return False


def _subsequence_score(q: str, t: str) -> float:
	"""Score *q* as a non-contiguous subsequence of *t*.

	Uses a single left-to-right scan.  Returns 0.0 if not all query
	characters appear in *t* in order.

	Scoring components:
	  • base              — flat reward for any subsequence match
	  • consecutive_bonus — reward for runs of adjacent matched characters
	  • position_bonus    — reward for the first match appearing early in *t*
	  • compactness_bonus — reward when matched characters are tightly grouped
	  • coverage_bonus    — reward when the query covers a large fraction of *t*
	"""
	n_q = len(q)
	n_t = len(t)

	qi = 0  # index into query
	ti = 0  # index into text

	first_match = -1
	last_match = -1
	prev_match = -2       # ti of the previous matched character
	consecutive = 0       # current run length
	max_consecutive = 0   # longest consecutive run so far
	total_matched = 0

	while qi < n_q and ti < n_t:
		if q[qi] == t[ti]:
			if first_match < 0:
				first_match = ti
			last_match = ti
			total_matched += 1

			if ti == prev_match + 1:
				consecutive += 1
				if consecutive > max_consecutive:
					max_consecutive = consecutive
			else:
				consecutive = 1

			prev_match = ti
			qi += 1
		ti += 1

	# All query characters must appear in order
	if qi < n_q:
		return 0.0

	# The span of text consumed by the match (smaller = better)
	span = last_match - first_match + 1

	# Compactness: 1.0 when all matched chars are adjacent, approaching 0
	# when they're spread across the whole string.
	compactness = n_q / span  # range (0, 1]

	# Position: 1.0 when first match is at index 0, 0.0 at the last char.
	position = 1.0 - (first_match / n_t)

	# Coverage: ratio of query length to text length.
	coverage = n_q / n_t

	base = 50.0
	consecutive_bonus = max_consecutive * 15.0   # up to ~15 × n_q
	compactness_bonus = compactness * 40.0        # up to 40
	position_bonus = position * 20.0              # up to 20
	coverage_bonus = coverage * 20.0              # up to 20

	return base + consecutive_bonus + compactness_bonus + position_bonus + coverage_bonus
