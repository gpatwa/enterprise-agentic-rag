# services/api/app/tools/calculator.py
from simpleeval import simple_eval


def calculate(expression: str) -> str:
    """
    Safely evaluates a mathematical expression using simpleeval.
    Prevents Remote Code Execution (RCE).
    """
    # 1. Length limit to prevent ReDoS or memory exhaustion
    if len(expression) > 100:
        return "Error: Expression too long."

    try:
        # simple_eval parses the AST and only allows math operators.
        # It has no access to globals, builtins, or os/sys modules.
        result = simple_eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"
