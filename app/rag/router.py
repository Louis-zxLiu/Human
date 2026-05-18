from app.rag.planner import QueryIntent, QueryPlanner


_planner = QueryPlanner()


def get_query_intent(query: str) -> QueryIntent:
    """
    Backward-compatible intent helper.

    The runtime now relies on a planner-first architecture, but several API
    surfaces still ask for a simple `FACT / ANALYTICS / RECOMMEND` label.
    """
    return _planner.plan(query).intent
