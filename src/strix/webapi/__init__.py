"""FastAPI research API exposing the shared STRIX research engine to the web UI.

The CLI and the web app call the same :func:`strix.agent.orchestrator.
run_research_question`; this package only adds an HTTP/job layer. The OpenAI API
key is loaded server-side and never sent to the browser.
"""
