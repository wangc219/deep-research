// Only user questions become follow-up context. The server resolves the parent again;
// this preview never supplies trusted context, old answers, or evidence to the API.
export function createFollowupDraft(task, mode = 'answer') {
  if (task?.status !== 'completed' || !task.id || !['answer', 'research'].includes(mode)) return null
  const questions = [...(task.context_questions || []), task.problem].filter((item) => typeof item === 'string' && item.trim())
  return {
    parent_task_id: task.id,
    questions: questions.slice(-3).map((item) => Array.from(item).slice(0, 2000).join('')),
    truncated: !!task.context_truncated || questions.length > 3 || questions.some((item) => Array.from(item).length > 2000),
    library_ids: [...task.library_ids],
    fields: {
      mode, problem: '', parser_version: task.parser_version || '', expected_result: task.expected_result || '', constraints: task.constraints || '',
      allow_public: false, allow_web_search: false, public_query: '', allow_external_model: false
    }
  }
}
