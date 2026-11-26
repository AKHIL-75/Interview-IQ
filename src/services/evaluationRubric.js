export const CONCEPTUAL_RUBRIC = 'conceptual-v2';
export const MIXED_RUBRICS = 'mixed';
export const OPTIONAL_SUGGESTIONS_HEADING = 'Suggestions to strengthen your answer';

export function suggestionText(text) {
  return text.replace(/^Optional:\s*/i, '');
}
