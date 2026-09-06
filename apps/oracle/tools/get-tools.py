"""Dynamic tool introspection for oracle.

Scans main.py's globals at runtime to discover every *_TOOL dict that matches
the ollama function-call schema, extracts name/description/parameters/required,
and returns them as a structured JSON payload the model can parse.

This means new tools added anywhere in main.py auto-discover — no schema copy/paste,
no registry updates, no restart required. The tool list and the code are ONE SOURCE.
"""

import json
import re


def _extract_tool_meta(tool_dict):
    """Parse one ollama function tool dict → (name, description, params_dict)."""
    func = tool_dict.get("function", {})
    if not isinstance(func, dict):
        return None
    name = func.get("name")
    desc = func.get("description", "")
    params = func.get("parameters", {})
    # Normalize properties → flat dict of {field: description}
    props = params.get("properties", {})
    required = params.get("required", [])
    return (name, desc, props, required)


def scan_tools(module_globals):
    """Scan globals for every *_TOOL value matching the function schema.

    Handles both single dicts (WEB_SEARCH_TOOL) and lists of dicts (FILE_TOOLS).
    Returns a list of {name, description, parameters, required} dicts.
    """
    tools = []
    for key in sorted(module_globals.keys()):
        if not key.endswith("_TOOL"):
            continue
        val = module_globals[key]
        if isinstance(val, dict):
            meta = _extract_tool_meta(val)
            if meta:
                name, desc, props, required = meta
                tools.append({
                    "name": name,
                    "description": desc,
                    "parameters": json.dumps(props),
                    "required_fields": ",".join(required),
                })
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    meta = _extract_tool_meta(item)
                    if meta:
                        name, desc, props, required = meta
                        tools.append({
                            "name": name,
                            "description": desc,
                            "parameters": json.dumps(props),
                            "required_fields": ",".join(required),
                        })
    return tools


def get_tools():
    """Main entry: import main.py, scan globals, return JSON string."""
    import sys
    from pathlib import Path

    # Resolve oracle's home directory from this file's location
    here = Path(__file__).resolve().parent.parent
    main_path = here / "main.py"

    # Add oracle dir to path so we can import main as a module
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))

    try:
        import main as oracle_main
        tools = scan_tools(vars(oracle_main))
        return json.dumps({
            "discovered_count": len(tools),
            "tools": tools,
        })
    except ImportError as e:
        return json.dumps({"error": f"Could not import main module: {e}"})


# Quick test when run directly
if __name__ == "__main__":
    print(get_tools())
