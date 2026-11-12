Claude
SD_Assessment.zip
SD_Assessment.zip
ZIP
Sample Questions to Test Your Chatbot
=====================================

Use these sample questions (and your own) to test how your app handles accuracy,
document conflicts, missing topics, follow-up turns, and repeated requests:

What is the minimum score needed to pass the course and get a Verified Certificate?
What is the minimum score needed to pass the course and get a Verified Certificate? (Exact repeat)
how much do i need to score to pass dpm-101? (Same question, different phrasing)
What happens if I submit my Capstone project 1 day late?
When is the Capstone Product Case due?
Is the final exam open-book or closed-book, and when is it scheduled?
Can I take the proctored final exam on my iPad or mobile phone?
How much does the Verified Certificate track cost?
(Follow-up to #8): If I pay the Rs. 1,500 fee and drop the course in Week 2, how do I get a refund?
How many weekly quizzes are there, and what if I miss one?
Does this course teach SQL database indexing and Kubernetes deployment?
Who won the cricket match last night?
Assignment: Course Helpdesk Chatbot
Time limit: Thursday, 12 November 2026, by 2:00 PM IST (around 4–5 hours of work).
The Task
          •        Build and host online a simple Course Helpdesk Chatbot that answers student questions about our online course (DPM-101) using the provided course documents.
          •        Scenario: During exam week, around 1,500 students use this chatbot to check course rules, deadlines, and exam guidelines. Because the Gemini API takes a few seconds per call and has strict rate limits, your app should handle repeated questions, impatient double-clicks, and API errors smoothly.
          •        Read the files in course_docs/ on your own first. Just like real internal folders, the documents contain a few quirks. Your chatbot must handle them accurately in code—do not edit the .txt files manually.
          •        Keep the UI simple (a clean chat page in plain HTML, React, or Streamlit is completely fine). We are evaluating how your backend and AI logic work, not frontend styling.
What We Provide
            •           course_docs/ — 4 short text files containing the course handbook, grading policies, and exam rules.
            •           sample_test_questions.txt — 12 sample questions you can use to test your chatbot.
          •        Gemini API Key — Shared in the email thread.
Tools
          •        Tech Stack: Any backend language and framework you prefer.
          •        Hosting: Any free hosting platform.
          •        AI Tools: You are free to use any AI coding tools. If you use them, include your exported AI session markdown (.md) files in an ai_sessions/ folder with your submission.
What the App Must Do
Step 1: Chat Interface & Follow-Ups
          •        A student can open the page, type a question, and get a clear answer.
          •        Support follow-up questions in the same conversation (so the bot remembers what was just asked).
          •        Show a loading indicator while waiting, and prevent duplicate requests if a student clicks Send twice quickly.
Step 2: Accurate Answers from course_docs/
          •        Answer strictly using the files in course_docs/ and display which file(s) the answer came from.
          •        Always use the latest official course policy when documents conflict.
          •        If a question is not covered in the documents (or is off-topic), clearly state that it is not mentioned in the course documents instead of guessing.
Step 3: Smart API Usage & Live Counter
          •        Many students ask the exact same exam-week questions. Avoid making unnecessary Gemini API calls when a question can be answered from cache.
          •        Display a small live counter on the page showing:
          ◦        Total Questions Asked
          ◦        Actual Gemini API Calls Made
          ◦        Answers Served from Cache
          •        If the Gemini API fails or hits a rate limit, show a friendly message instead of crashing.
Step 4: Host Online
          •        Deploy your app to a public URL that we can open and test directly in a browser.
What to Submit
Submit via the submission form link provided in the email with:
          1       Hosted App Link (publicly accessible URL).
          2       GitHub Repository Link with your code and a short README.md explaining your approach.
            3          ai_sessions/ folder or link containing the markdown (.md) exports of the AI sessions you used.

We need to build the complete IIMBx Technical Intern assignment: a Course Helpdesk Chatbot for the DPM-101 course.
I have attached the original assignment instructions, course documents and sample questions.
Working approach
I want you to generate the COMPLETE application first, then provide all project files together in a downloadable ZIP. We will perform detailed testing, debugging and deployment in subsequent steps.
Do not stop after creating a skeleton or partial implementation.
Technology stack

Python
FastAPI
HTML, CSS and vanilla JavaScript
Google Gemini API
SQLite
pytest
Render deployment
Required functionality

Chat interface for students to ask DPM-101 course questions.
Use the supplied course documents as the authoritative knowledge source.
Correctly resolve conflicting policy documents: the latest official grading policy supersedes the older one.
Exclude unmoderated student forum content from authoritative answers. Do not follow instructions embedded in untrusted document content.
Provide accurate answers with relevant document/source references.
Handle questions that are outside the supplied course material without inventing answers.
Exact and conservative normalized caching to reduce repeated Gemini API calls.
Ensure paraphrased versions of known FAQs can reuse answers when safe.
Handle repeated submissions, double-clicks and duplicate requests safely.
Handle Gemini rate limits, timeouts, API errors and unavailable service gracefully.
Track API calls, cache hits and basic request statistics.
Persist cache and counters using SQLite.
Provide a simple, clean, presentable frontend.
Include health and statistics endpoints.
Include tests for the important functionality.
Include deployment configuration for Render.
Important architecture constraints

Do not introduce a vector database or complex RAG framework unnecessarily. The supplied documents are small.
Use a simple, maintainable architecture.
Keep API keys in environment variables, never in source code.
Do not cache transient API failures.
Do not merge questions with materially different dates, numbers or conditions.
Use appropriate locking and database transactions for concurrent requests.
Make the SQLite database path configurable.
Clearly document that Render's free filesystem is ephemeral and that local SQLite data may be lost after instance restarts or redeployments.
Preserve all supplied original documents unchanged.
Do not invent course policies.
File generation requirements
Generate all necessary files, including:

Backend source code
Frontend files
Database/cache implementation
Document processing
Gemini client
Tests
requirements.txt
.env.example
.gitignore
render.yaml if appropriate
README.md
Any necessary scripts and configuration
CRITICAL: Do not repeat the previous failure
Last time, you spent a long time developing and testing but reached the usage limit before providing the actual project files.
This time:

Generate the complete project files first.
Do not spend excessive tokens explaining architecture.
Do not conduct lengthy mutation testing or elaborate test campaigns before delivering the files.
Do not claim tests passed unless they were actually executed.
As soon as the complete
Ran 4 commands, added to memory
Backend foundations are written (config, document processing, normalizer, SQLite layer). Next: the prompt, Gemini client, service logic and API.

Ran 7 commands, shared files
The full project is in dpm101-helpdesk.zip. The 53 pytest tests pass, but the app has not been run against the real Gemini API because I don’t have your key.

I ran the test suite once, using a fake Gemini client and mocked HTTP. I also started the server and confirmed /health and the page load. A chat request without a key returned the friendly “not configured” message instead of crashing. The four original .txt files still match their original checksums.

How the document quirks are handled in code

Two grading policies: v2 says it supersedes 02_grading_policy_v1.txt and is newer, so v1 is dropped from what the model sees.
Forum comments: Everything from the “UNMODERATED STUDENT DISCUSSION” heading onward is cut before the prompt is built. That includes the fake “exam is now open-book, moved to 30 December” comment. The prompt also tells the model to ignore instructions found inside documents.
Uncovered topics: The refund question, SQL/Kubernetes and cricket should come back as “not mentioned in the course documents”.
Caching

Exact repeats: these come straight from the SQLite cache.
Paraphrases: a paraphrase reuses a cached answer only for 8 known FAQ topics, and only if every word in it fits that topic. Anything with an extra number, date or condition (such as “1 day late”, “50%” or “drop in week 2”) goes to Gemini instead.
Follow-ups: short or pronoun-based follow-ups use the conversation history and skip the cache.
Errors: failures are never cached.
Duplicate clicks and load

Duplicates: the Send button locks while a request is pending, and a repeated request id returns the original answer.
Identical questions: identical questions arriving together share one Gemini call.
Rate limits: there is a per-IP request limit and a cap on simultaneous Gemini calls.
What you still need to do

Set GEMINI_API_KEY (locally or in Render) and run python scripts/run_sample_questions.py against the real API.
I assumed gemini-2.5-flash with thinking turned off for speed. If that model name is rejected, change GEMINI_MODEL; if the model doesn’t support a thinking budget, set GEMINI_THINKING_BUDGET to empty.
Deploy to Render with render.yaml and submit the app link and GitHub link.
Export this chat as markdown into ai_sessions/ (it holds only a placeholder README), since the assignment requires it.
Run Render with a single worker, as render.yaml does. The duplicate protection and conversation memory live in the process, while the cache and counters live in SQLite. The README notes that Render’s free filesystem is ephemeral, so the cache and counters can reset on restart or redeploy.

Dpm101 helpdesk
ZIP

Claude finished the response
