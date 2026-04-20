---
name: summary-prd-planning
description: Consolidates decisions and recommendations from PRD planning session. Creates structured summary ready for use in the next stage of generating the complete document.
argument-hint: [latest-round-answers] [conversation-language]
disable-model-invocation: false
user-invocable: true
---

You are an AI assistant whose task is to summarize a conversation about PRD (Product Requirements Document) planning for MVP and prepare a concise summary for the next development stage. In the conversation history you will find the following information:
1. Project description
2. Identified user problem
3. Conversation history containing questions and answers
4. Recommendations regarding PRD content

Your task is to:
1. Summarize the conversation history, focusing on all decisions related to PRD planning.
2. Match the model's recommendations to the answers given in the conversation history. Identify which recommendations are relevant based on the discussion.
3. Prepare a detailed conversation summary that includes:
   a. Main functional requirements of the product
   b. Key user stories and usage paths
   c. Important success criteria and ways to measure them
   d. Any unresolved issues or areas requiring further clarification
4. Format the results as follows:

<conversation_summary>
<decisions>
[List decisions made by the user, numbered].
</decisions>

<matched_recommendations>
[List of the most relevant recommendations matched to the conversation, numbered]
</matched_recommendations>

<prd_planning_summary>
[Provide a detailed summary of the conversation, including the elements listed in step 3].
</prd_planning_summary>

<unresolved_issues>
[List any unresolved issues or areas requiring further clarification, if any exist]
</unresolved_issues>
</conversation_summary>

The final result should contain only content in markdown format. Ensure that your summary is clear, concise, and provides valuable information for the next stage of creating the PRD. Save summary in `.ai/prd-planning-summary.md`.

<latest_round_answers>
$ARGUMENTS[0]
</latest_round_answers>

CONVERSATE AND ASK QUESTIONS IN THE USER'S LANGUAGE, UNLESS THE USER INSTRUCTS OTHERWISE. PLEASE USE $ARGUMENTS[1] or if not set English. ALL FILES SHOULD BE GENERATED IN ENGLISH.