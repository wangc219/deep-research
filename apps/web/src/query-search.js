const SEARCH_SEPARATOR_PATTERN = /[\p{P}\p{S}\s]+/gu;

export function normalizeQuerySearchText(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .toLocaleLowerCase('zh-CN')
    .replace(SEARCH_SEPARATOR_PATTERN, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function searchableFields(item) {
  const references = Array.isArray(item?.source_references)
    ? item.source_references.flatMap(reference => [
        reference?.title,
        reference?.relevance_note,
        reference?.source_kind,
      ])
    : [];
  return [
    item?.query,
    item?.supplemental_information,
    item?.generation_rationale,
    item?.source_disclaimer,
    ...references,
  ].map(normalizeQuerySearchText).filter(Boolean);
}

function matchScore(item, search) {
  const normalizedSearch = normalizeQuerySearchText(search);
  if (!normalizedSearch) return 0;
  const tokens = [...new Set(normalizedSearch.split(' ').filter(Boolean))];
  const fields = searchableFields(item);
  const compactFields = fields.map(field => field.replaceAll(' ', ''));
  const compactSearch = normalizedSearch.replaceAll(' ', '');
  const title = normalizeQuerySearchText(item?.query);
  const compactTitle = title.replaceAll(' ', '');

  // Multiple keywords use AND semantics, but each keyword may appear in a
  // different indexed field. This handles Chinese queries entered with spaces
  // and punctuation without requiring an exact continuous substring.
  if (tokens.some(token => {
    const compactToken = token.replaceAll(' ', '');
    return !compactFields.some(field => field.includes(compactToken));
  })) return -1;

  let score = 0;
  if (compactTitle.includes(compactSearch)) score += 120;
  else if (compactFields.some(field => field.includes(compactSearch))) score += 60;
  for (const token of tokens) {
    const compactToken = token.replaceAll(' ', '');
    if (compactTitle.includes(compactToken)) score += 24;
    else if (compactFields[1]?.includes(compactToken)) score += 10;
    else if (compactFields.some(field => field.includes(compactToken))) score += 5;
  }
  if (compactTitle.startsWith(tokens[0]?.replaceAll(' ', '') || '')) score += 8;
  return score;
}

export function searchQueryItems(items, search) {
  if (!normalizeQuerySearchText(search)) return items;
  return items
    .map((item, index) => ({item, index, score: matchScore(item, search)}))
    .filter(result => result.score >= 0)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map(result => result.item);
}
