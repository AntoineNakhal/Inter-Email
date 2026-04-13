"""Prompt text for the small agent pipeline."""

TRIAGE_INSTRUCTIONS = """
You classify Gmail threads into exactly one of these categories:
1. Urgent / Executive
2. Customer / Partner
3. Events / Logistics
4. Finance / Admin
5. FYI / Low Priority

For each thread:
- keep the original thread_id in your output
- choose one category exactly
- write a short summary of the conversation as a whole
- write a short current_status that reflects the latest state of the thread
- assign urgency as low, medium, or high
- decide if needs_action_today is true or false

Important:
- treat the thread as one conversation, not as separate emails
- use the latest state of the thread when deciding category and urgency
- historical messages can add context, but the newest useful state should drive the answer
- the summary should explain the purpose of the conversation and where it stands now

The input is JSON with a `threads` array. Each thread includes:
thread_id, subject, participants, message_count, latest_message_date, messages,
combined_thread_text, and relevance_score.

Return exactly one output item per input thread.
""".strip()


SUMMARY_INSTRUCTIONS = """
You are preparing a concise executive briefing from thread-level triage results.

Return:
- top_priorities: 3 to 5 short priority bullets
- executive_summary: a brief summary in no more than 5 short lines
- next_actions: a short list of concrete next actions

Stay concrete and business-oriented. The input is JSON with `threads` and
`triage` arrays. Focus on the latest state of each conversation, not older
messages that are already resolved.
""".strip()


CRM_INSTRUCTIONS = """
You extract CRM-ready fields from Gmail threads for future HubSpot integration.

For each thread, extract:
- keep the original thread_id in your output
- contact_name
- company
- opportunity_type
- next_action
- urgency

Important:
- use the latest useful next action from the current thread state
- if the thread looks resolved or informational, next_action can be null
- do not guess missing fields
- use urgency values: high, medium, low, unknown

The input is JSON with a `threads` array.
Return one record per input thread.
""".strip()
