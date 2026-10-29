"""The advisor agent.

A LangGraph state graph over the application state LeapAshore keeps: intent routing, an evidence
gate in front of any answer about an official requirement, a ReAct loop with a step cap, and an
interrupt that holds every portfolio change until the applicant confirms it.
"""
